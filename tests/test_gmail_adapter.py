"""GmailAdapter.fetch: the owed-reply heuristic, over a fake googleapiclient service."""

from datetime import timedelta

import pytest

from command_center.adapters import gmail, gmail_mail
from command_center.core.errors import AuthExpired, FatalError, TransientError
from command_center.core.schema import Event, event_id
from gmail_support import (
    CREDS,
    ME,
    NOW,
    WINDOW,
    FakeGmail,
    hours_ago,
    http_error,
    make_adapter,
    message,
    thread,
)


async def fetch(
    fake: FakeGmail, *, vip_senders: tuple[str, ...] = (), muted_senders: tuple[str, ...] = ()
) -> list[Event]:
    adapter = make_adapter(fake, vip_senders=vip_senders, muted_senders=muted_senders)
    return await adapter.fetch(CREDS, WINDOW)


async def test_a_thread_whose_last_message_is_to_the_user_is_owed() -> None:
    last = message(sent=hours_ago(5))
    fake = FakeGmail({"t1": thread("t1", message(sent=hours_ago(30), sender=ME), last)})

    [event] = await fetch(fake)

    assert event.source == "gmail"
    assert event.kind == "email"
    assert event.status == "owed"
    assert event.title == "Question about the project"
    assert event.start == hours_ago(5)
    assert event.due is None
    assert event.urgency == 0
    assert event.id == event_id("gmail", "t1")
    assert event.link == "https://mail.google.com/mail/u/0/#all/t1"
    assert event.fetched_at == NOW


async def test_raw_holds_the_sender_name_and_snippet_only() -> None:
    fake = FakeGmail({"t1": thread("t1", message(sent=hours_ago(1), snippet="Don&#39;t forget"))})

    [event] = await fetch(fake)

    assert event.raw == {"sender": "Alex Doe", "snippet": "Don't forget"}
    assert "alex@school.edu" not in str(event.model_dump())


async def test_addresses_and_numbers_in_the_snippet_are_redacted() -> None:
    body = message(sent=hours_ago(1), snippet="Reach me at alex@school.edu or 801-555-1234")
    [event] = await fetch(FakeGmail({"t1": thread("t1", body)}))

    assert event.raw["snippet"] == "Reach me at [email] or [number]"


@pytest.mark.parametrize("bad_date", ["", "yesterday"])
async def test_a_malformed_internal_date_is_fatal(bad_date: str) -> None:
    broken = message(sent=hours_ago(1)) | {"internalDate": bad_date}

    with pytest.raises(FatalError, match="unexpected response"):
        await fetch(FakeGmail({"t1": thread("t1", broken)}))


async def test_a_display_name_that_is_an_address_is_not_kept() -> None:
    sent = message(sent=hours_ago(1), sender='"alex@school.edu" <alex@school.edu>')
    [event] = await fetch(FakeGmail({"t1": thread("t1", sent)}))

    assert event.raw["sender"] == ""


async def test_a_thread_the_user_answered_last_is_not_owed() -> None:
    reply = message(sent=hours_ago(1), sender=ME, to="alex@school.edu", labels=("SENT",))
    fake = FakeGmail({"t1": thread("t1", message(sent=hours_ago(4)), reply)})

    assert await fetch(fake) == []


async def test_a_last_message_from_the_users_address_is_not_owed_even_without_a_sent_label() -> (
    None
):
    mine = message(sent=hours_ago(1), sender=f"Me <{ME.upper()}>", labels=("INBOX",))
    assert await fetch(FakeGmail({"t1": thread("t1", message(sent=hours_ago(3)), mine)})) == []


async def test_an_unsent_draft_does_not_count_as_the_last_message() -> None:
    draft = message(sent=hours_ago(1), sender=ME, to="alex@school.edu", labels=("DRAFT",))
    fake = FakeGmail({"t1": thread("t1", message(sent=hours_ago(4)), draft)})

    [event] = await fetch(fake)

    assert event.start == hours_ago(4)


async def test_a_thread_that_only_copies_the_user_is_not_owed() -> None:
    cc_only = message(sent=hours_ago(2), to="team@school.edu", cc=ME)
    assert await fetch(FakeGmail({"t1": thread("t1", cc_only)})) == []


@pytest.mark.parametrize("label", ["STARRED", "IMPORTANT"])
async def test_a_starred_or_important_thread_is_owed_even_when_only_copied(label: str) -> None:
    cc_only = message(sent=hours_ago(2), to="team@school.edu", cc=ME, labels=("INBOX", label))
    [event] = await fetch(FakeGmail({"t1": thread("t1", cc_only)}))

    assert event.status == "owed"


async def test_a_vip_sender_is_owed_even_when_only_copied() -> None:
    cc_only = message(sent=hours_ago(2), to="team@school.edu", cc=ME)
    fake = FakeGmail({"t1": thread("t1", cc_only)})

    assert len(await fetch(fake, vip_senders=("@School.edu",))) == 1


async def test_a_muted_sender_is_never_owed() -> None:
    fake = FakeGmail({"t1": thread("t1", message(sent=hours_ago(2)))})

    assert await fetch(fake, muted_senders=(" Alex@school.edu ",)) == []


@pytest.mark.parametrize(
    ("sender", "extra"),
    [
        ("Alex <alex@school.edu>", {"List-Unsubscribe": "<mailto:u@school.edu>"}),
        ("Alex <alex@school.edu>", {"List-Id": "<club.school.edu>"}),
        ("Alex <alex@school.edu>", {"Precedence": "bulk"}),
        ("Alex <alex@school.edu>", {"Auto-Submitted": "auto-generated"}),
        ("School <noreply@school.edu>", {}),
        ("School <no-reply@school.edu>", {}),
        ("School <do.not.reply@school.edu>", {}),
    ],
)
async def test_bulk_and_automated_mail_is_not_owed(sender: str, extra: dict[str, str]) -> None:
    bulk = message(sent=hours_ago(2), sender=sender, extra=extra)
    assert await fetch(FakeGmail({"t1": thread("t1", bulk)})) == []


async def test_auto_submitted_no_is_a_normal_message() -> None:
    normal = message(sent=hours_ago(2), extra={"Auto-Submitted": "no"})
    assert len(await fetch(FakeGmail({"t1": thread("t1", normal)}))) == 1


async def test_a_thread_waiting_more_than_two_days_is_overdue() -> None:
    old = message(sent=NOW - timedelta(days=2, minutes=1))
    [event] = await fetch(FakeGmail({"t1": thread("t1", old)}))

    assert event.status == "overdue"


async def test_a_thread_waiting_exactly_two_days_is_still_owed() -> None:
    [event] = await fetch(FakeGmail({"t1": thread("t1", message(sent=NOW - timedelta(days=2)))}))

    assert event.status == "owed"


async def test_a_thread_outside_the_window_is_left_out() -> None:
    old = message(sent=WINDOW.start - timedelta(days=1))
    assert await fetch(FakeGmail({"t1": thread("t1", old)})) == []


async def test_a_missing_subject_gets_a_placeholder_and_a_long_one_is_trimmed() -> None:
    blank = message(sent=hours_ago(1), subject="")
    long = message(sent=hours_ago(2), subject="word " * 100)
    events = await fetch(FakeGmail({"t1": thread("t1", blank), "t2": thread("t2", long)}))

    titles = {event.id: event.title for event in events}
    assert titles[event_id("gmail", "t1")] == "(no subject)"
    assert len(titles[event_id("gmail", "t2")]) == gmail_mail.TITLE_LIMIT


async def test_an_encoded_subject_is_decoded() -> None:
    encoded = message(sent=hours_ago(1), subject="=?UTF-8?B?Q2Fmw6k=?=")
    [event] = await fetch(FakeGmail({"t1": thread("t1", encoded)}))

    assert event.title == "Café"


async def test_the_query_and_metadata_headers_are_requested_and_pages_followed() -> None:
    fake = FakeGmail(
        {f"t{i}": thread(f"t{i}", message(sent=hours_ago(i + 1))) for i in range(4)}, pages=2
    )

    events = await fetch(fake)

    assert len(events) == 4
    assert [call["pageToken"] for call in fake.list_calls] == [None, "1"]
    assert all(call["q"] == gmail_mail.QUERY for call in fake.list_calls)
    assert all(call["userId"] == "me" for call in fake.list_calls)
    for call in fake.get_calls:
        assert call["format"] == "metadata"
        assert call["metadataHeaders"] == [
            *("From", "To", "Cc", "Subject"),
            *("List-Unsubscribe", "List-Id", "Precedence", "Auto-Submitted"),
        ]


async def test_a_failed_thread_fetch_raises_instead_of_returning_the_rest() -> None:
    fake = FakeGmail(
        {
            "t1": thread("t1", message(sent=hours_ago(1))),
            "t2": thread("t2", message(sent=hours_ago(2))),
        },
        get_errors={"t2": http_error(500)},
    )

    with pytest.raises(TransientError):
        await fetch(fake)


async def test_more_pages_than_the_cap_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gmail, "MAX_PAGES", 1)
    fake = FakeGmail(
        {f"t{i}": thread(f"t{i}", message(sent=hours_ago(1))) for i in range(4)}, pages=2
    )

    with pytest.raises(FatalError):
        await fetch(fake)


async def test_a_response_without_the_expected_fields_is_fatal() -> None:
    fake = FakeGmail(profile={"unexpected": True})

    with pytest.raises(FatalError, match="unexpected response"):
        await fetch(fake)


async def test_fetch_without_a_refresh_token_needs_a_reconnect() -> None:
    adapter = make_adapter(FakeGmail())

    with pytest.raises(AuthExpired):
        await adapter.fetch({"client_json": CREDS["client_json"]}, WINDOW)
