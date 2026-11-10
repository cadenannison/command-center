"""Daily summary model, prompt building and the provider-free template summary."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from builders import make_event
from command_center.core.schema import Event
from command_center.core.summary import (
    ITEM_TEXT_LIMIT,
    MAX_PROMPT_ITEMS,
    DailySummary,
    build_prompt,
    template_summary,
)

TODAY = date(2026, 11, 7)
EMPTY_TAIL = "Today is 2026-11-07.\nItems:\n(none)"


def _prompt(*events: Event, include_email: bool = True) -> str:
    return build_prompt(list(events), include_email, TODAY)


def _lines(prompt: str) -> list[str]:
    return [line for line in prompt.splitlines() if line.startswith("- [")]


def test_daily_summary_defaults_to_empty_lists() -> None:
    summary = DailySummary(headline="Busy day")

    assert summary.priorities == []
    assert summary.heads_up == []


def test_daily_summary_is_frozen() -> None:
    summary = DailySummary(headline="Busy day")

    with pytest.raises(ValidationError):
        summary.headline = "changed"  # pyright: ignore[reportAttributeAccessIssue]


def test_daily_summary_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        DailySummary.model_validate({"headline": "x", "mood": "good"})


def test_daily_summary_requires_a_headline() -> None:
    with pytest.raises(ValidationError):
        DailySummary.model_validate({})


def test_daily_summary_accepts_a_300_character_headline_and_rejects_301() -> None:
    assert DailySummary(headline="h" * 300).headline == "h" * 300
    with pytest.raises(ValidationError):
        DailySummary(headline="h" * 301)


@pytest.mark.parametrize("field", ["priorities", "heads_up"])
def test_daily_summary_list_accepts_ten_items_and_rejects_eleven(field: str) -> None:
    assert (
        len(getattr(DailySummary.model_validate({"headline": "x", field: ["a"] * 10}), field)) == 10
    )
    with pytest.raises(ValidationError):
        DailySummary.model_validate({"headline": "x", field: ["a"] * 11})


@pytest.mark.parametrize("field", ["priorities", "heads_up"])
def test_daily_summary_list_item_accepts_300_characters_and_rejects_301(field: str) -> None:
    DailySummary.model_validate({"headline": "x", field: ["a" * 300]})
    with pytest.raises(ValidationError):
        DailySummary.model_validate({"headline": "x", field: ["a" * 301]})


def test_daily_summary_schema_is_plain_strings_and_string_lists() -> None:
    properties = DailySummary.model_json_schema()["properties"]

    assert properties["headline"]["type"] == "string"
    assert properties["priorities"]["type"] == "array"
    assert properties["priorities"]["items"]["type"] == "string"
    assert properties["heads_up"]["items"]["type"] == "string"


def test_limits_have_the_documented_values() -> None:
    assert MAX_PROMPT_ITEMS == 40
    assert ITEM_TEXT_LIMIT == 80


def test_prompt_has_instructions_then_date_then_items() -> None:
    prompt = _prompt(make_event(title="Read chapter 3"))

    assert "daily briefing" in prompt
    assert "ONLY" in prompt
    for key in ("headline", "priorities", "heads_up"):
        assert key in prompt
    assert "untrusted" in prompt
    assert prompt.endswith("Today is 2026-11-07.\nItems:\n- [event] Read chapter 3")
    assert prompt.index("untrusted") < prompt.index("Today is")


def test_prompt_with_no_events_says_none() -> None:
    assert _prompt().endswith(EMPTY_TAIL)


def test_prompt_formats_kind_title_and_due_date() -> None:
    due = datetime(2026, 11, 9, 23, 59, tzinfo=UTC)

    prompt = _prompt(
        make_event(id="a", kind="assignment", title="Essay", due=due),
        make_event(id="b", kind="event", title="Lecture"),
    )

    assert _lines(prompt) == ["- [assignment] Essay (due 2026-11-09)", "- [event] Lecture"]


def test_prompt_due_date_is_the_date_in_the_due_datetimes_own_timezone() -> None:
    due = datetime(2026, 11, 9, 23, 30, tzinfo=timezone(timedelta(hours=-8)))

    prompt = _prompt(make_event(kind="assignment", title="Essay", due=due))

    assert "(due 2026-11-09)" in prompt
    assert "2026-11-10" not in prompt


def test_prompt_keeps_input_order() -> None:
    prompt = _prompt(
        make_event(id="1", title="zeta"),
        make_event(id="2", title="alpha"),
        make_event(id="3", title="mid"),
    )

    assert _lines(prompt) == ["- [event] zeta", "- [event] alpha", "- [event] mid"]


def test_prompt_skips_email_events_when_email_is_off() -> None:
    prompt = _prompt(
        make_event(id="1", kind="email", title="Lunch plans"),
        make_event(id="2", title="Lecture"),
        include_email=False,
    )

    assert _lines(prompt) == ["- [event] Lecture"]
    assert "Lunch plans" not in prompt


def test_prompt_with_only_email_and_email_off_says_none() -> None:
    prompt = _prompt(make_event(kind="email", title="Lunch plans"), include_email=False)

    assert prompt.endswith(EMPTY_TAIL)


def test_prompt_includes_the_email_subject_when_email_is_on() -> None:
    prompt = _prompt(make_event(kind="email", title="Lunch plans"), include_email=True)

    assert _lines(prompt) == ["- [email] Lunch plans"]


def test_prompt_collapses_whitespace_runs_and_newlines() -> None:
    prompt = _prompt(make_event(title="  Read \n\n chapter\t\t3  "))

    assert _lines(prompt) == ["- [event] Read chapter 3"]


def test_prompt_skips_items_that_are_empty_after_cleaning() -> None:
    prompt = _prompt(make_event(id="1", title="  \n\t "), make_event(id="2", title="Kept"))

    assert _lines(prompt) == ["- [event] Kept"]


def test_prompt_with_only_blank_titles_says_none() -> None:
    assert _prompt(make_event(title=" \n ")).endswith(EMPTY_TAIL)


def test_prompt_redacts_numbers_in_titles() -> None:
    prompt = _prompt(make_event(title="Call 801-555-1234 about lab"))

    assert _lines(prompt) == ["- [event] Call [number] about lab"]


def test_prompt_redacts_before_trimming() -> None:
    # Trimmed first, the cut would leave "80155": a partial number that no longer looks like one.
    title = "a" * 73 + " 8015551234"

    line = _lines(_prompt(make_event(title=title)))[0]

    assert not any(char.isdigit() for char in line)


def test_prompt_trims_long_titles_to_the_item_limit() -> None:
    line = _lines(_prompt(make_event(title="word " * 100)))[0]

    text = line.removeprefix("- [event] ")
    assert len(text) == ITEM_TEXT_LIMIT
    assert text.endswith("…")


def test_prompt_keeps_a_title_of_exactly_the_limit() -> None:
    title = ("ab " * ITEM_TEXT_LIMIT)[:ITEM_TEXT_LIMIT]

    assert _lines(_prompt(make_event(title=title))) == [f"- [event] {title}"]


def test_prompt_lists_at_most_max_items_in_input_order() -> None:
    events = [make_event(id=str(n), title=f"item {n}") for n in range(MAX_PROMPT_ITEMS + 10)]

    lines = _lines(_prompt(*events))

    assert len(lines) == MAX_PROMPT_ITEMS
    assert lines[0] == "- [event] item 0"
    assert lines[-1] == f"- [event] item {MAX_PROMPT_ITEMS - 1}"


def test_prompt_skipped_items_do_not_use_up_the_item_limit() -> None:
    blanks = [make_event(id=f"b{n}", title=" ") for n in range(5)]
    events = [make_event(id=str(n), title=f"item {n}") for n in range(MAX_PROMPT_ITEMS)]

    assert len(_lines(_prompt(*blanks, *events))) == MAX_PROMPT_ITEMS


def test_prompt_never_contains_an_address_from_a_subject_or_a_title() -> None:
    prompt = _prompt(
        make_event(id="1", kind="email", title="Re: send to fake-person@example.com now"),
        make_event(id="2", kind="event", title="Call fake.name@example.org"),
    )

    assert "fake-person@example.com" not in prompt
    assert "fake.name@example.org" not in prompt
    assert "fake-person" not in prompt
    assert "fake.name" not in prompt
    assert "[email]" in prompt


def test_prompt_never_contains_anything_but_kind_title_and_due() -> None:
    event = make_event(
        id="evt-secret-id",
        user_id="fake-user-q",
        source="fake-source-xyz",
        kind="email",
        title="Subject line",
        start=datetime(2031, 3, 4, 5, 6, tzinfo=UTC),
        end=datetime(2031, 3, 4, 7, 8, tzinfo=UTC),
        due=datetime(2026, 11, 9, 1, 2, tzinfo=UTC),
        urgency=77,
        link="https://example.com/secret-link",
        status="secret-status",
        raw={"from": "fake-sender@example.com", "body": "secret body text"},
    )

    prompt = _prompt(event)

    assert _lines(prompt) == ["- [email] Subject line (due 2026-11-09)"]
    for leaked in (
        "evt-secret-id",
        "fake-user-q",
        "fake-source-xyz",
        "2031",
        "05:06",
        "07:08",
        "01:02",
        "77",
        "secret-link",
        "secret-status",
        "fake-sender",
        "secret body text",
        "body",
    ):
        assert leaked not in prompt


def test_prompt_is_deterministic() -> None:
    events = [make_event(id="1", title="a"), make_event(id="2", title="b")]

    assert _prompt(*events) == _prompt(*events)


_LOCAL = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789._-", min_size=1, max_size=12)
_DOMAIN = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=10)
_TLD = st.sampled_from(["com", "org", "edu", "io"])
_NO_AT = st.text(max_size=40).filter(lambda text: "@" not in text)


@given(local=_LOCAL, domain=_DOMAIN, tld=_TLD, before=_NO_AT, after=_NO_AT)
def test_prompt_never_leaks_a_generated_address_in_a_title(
    local: str, domain: str, tld: str, before: str, after: str
) -> None:
    address = f"{local}@{domain}.{tld}"
    title = f"{before} {address} {after}"

    for kind in ("event", "email"):
        prompt = _prompt(make_event(kind=kind, title=title))

        assert address not in prompt


def _template(*events: Event, today: date = TODAY) -> DailySummary:
    return template_summary(list(events), today)


def test_template_with_no_events_says_nothing_scheduled() -> None:
    assert _template().headline == "Nothing scheduled for 2026-11-07"
    assert _template().priorities == []
    assert _template().heads_up == []


def test_template_ignores_weather_when_counting() -> None:
    summary = _template(make_event(kind="weather", title="Sunny"))

    assert summary.headline == "Nothing scheduled for 2026-11-07"
    assert summary.priorities == []


def test_template_headline_is_singular_for_one_item() -> None:
    assert _template(make_event()).headline == "1 item to look at on 2026-11-07"


def test_template_headline_is_plural_for_several_items() -> None:
    summary = _template(make_event(id="1"), make_event(id="2"), make_event(id="3"))

    assert summary.headline == "3 items to look at on 2026-11-07"


def test_template_priorities_skip_zero_urgency() -> None:
    summary = _template(make_event(id="1", title="Calm", urgency=0))

    assert summary.priorities == []


def test_template_priorities_sort_by_urgency_then_title_then_id_and_cap_at_three() -> None:
    summary = _template(
        make_event(id="1", title="b", urgency=50),
        make_event(id="2", title="a", urgency=50),
        make_event(id="3", title="z", urgency=90),
        make_event(id="4", title="c", urgency=50),
        make_event(id="5", title="y", urgency=10),
    )

    assert summary.priorities == ["z", "a", "b"]


def test_template_priorities_break_title_ties_by_id() -> None:
    summary = _template(
        make_event(id="2", title="same", urgency=50, due=datetime(2026, 11, 8, tzinfo=UTC)),
        make_event(id="1", title="same", urgency=50),
    )

    assert summary.priorities == ["same", "same (due 2026-11-08)"]


def test_template_priorities_append_the_due_date() -> None:
    due = datetime(2026, 11, 9, 12, tzinfo=UTC)

    summary = _template(make_event(kind="assignment", title="Essay", urgency=90, due=due))

    assert summary.priorities == ["Essay (due 2026-11-09)"]


def test_template_priorities_exclude_weather_even_with_urgency() -> None:
    summary = _template(make_event(kind="weather", title="Storm", urgency=99))

    assert summary.priorities == []


def test_template_collapses_whitespace_and_trims_titles() -> None:
    summary = _template(
        make_event(id="1", title="Read \n  chapter", urgency=50),
        make_event(id="2", title="x" * 200, urgency=40),
    )

    assert summary.priorities[0] == "Read chapter"
    assert summary.priorities[1] == "x" * (ITEM_TEXT_LIMIT - 1) + "…"


def test_template_uses_titles_as_is_without_redaction() -> None:
    summary = _template(make_event(title="Call jo@example.com 8015551234", urgency=50))

    assert summary.priorities == ["Call jo@example.com 8015551234"]


def test_template_heads_up_marks_overdue_items() -> None:
    summary = _template(
        make_event(
            kind="assignment", title="Essay", urgency=100, due=datetime(2026, 11, 6, 23, tzinfo=UTC)
        )
    )

    assert summary.heads_up == ["Overdue: Essay"]


def test_template_heads_up_lists_an_item_due_in_two_days() -> None:
    summary = _template(
        make_event(id="2", title="Soon", urgency=90, due=datetime(2026, 11, 9, 1, tzinfo=UTC)),
    )

    assert summary.heads_up == ["Due 2026-11-09: Soon"]


def test_template_heads_up_due_today_is_skipped_but_tomorrow_and_day_after_are_listed() -> None:
    summary = _template(
        make_event(id="0", title="Now", urgency=90, due=datetime(2026, 11, 7, 20, tzinfo=UTC)),
        make_event(id="1", title="Tomorrow", urgency=90, due=datetime(2026, 11, 8, 9, tzinfo=UTC)),
        make_event(id="2", title="Later", urgency=90, due=datetime(2026, 11, 9, 9, tzinfo=UTC)),
        make_event(id="3", title="Far", urgency=90, due=datetime(2026, 11, 10, 9, tzinfo=UTC)),
    )

    assert summary.heads_up == ["Due 2026-11-08: Tomorrow", "Due 2026-11-09: Later"]


def test_template_heads_up_requires_urgency_and_a_due_date() -> None:
    summary = _template(
        make_event(id="1", title="Calm", urgency=0, due=datetime(2026, 11, 1, tzinfo=UTC)),
        make_event(id="2", title="Undated", urgency=90),
    )

    assert summary.heads_up == []


def test_template_heads_up_sorts_by_due_then_id_and_caps_at_five() -> None:
    summary = _template(
        *[
            make_event(
                id=f"{n}",
                title=f"t{n}",
                urgency=50,
                due=datetime(2026, 11, 1 + (n % 3), 9, tzinfo=UTC),
            )
            for n in range(9)
        ]
    )

    assert summary.heads_up == [
        "Overdue: t0",
        "Overdue: t3",
        "Overdue: t6",
        "Overdue: t1",
        "Overdue: t4",
    ]


def test_template_heads_up_uses_the_due_date_in_its_own_timezone() -> None:
    due = datetime(2026, 11, 6, 23, 30, tzinfo=timezone(timedelta(hours=-8)))

    summary = _template(make_event(title="Edge", urgency=90, due=due))

    assert summary.heads_up == ["Overdue: Edge"]


def test_template_counts_email_events_it_is_given() -> None:
    summary = _template(make_event(kind="email", title="Reply to Sam", urgency=75))

    assert summary.headline == "1 item to look at on 2026-11-07"
    assert summary.priorities == ["Reply to Sam"]


def test_template_is_deterministic_and_does_not_depend_on_input_order() -> None:
    events = [make_event(id=str(n), title=f"t{n}", urgency=10 + n) for n in range(6)]

    assert template_summary(events, TODAY) == template_summary(events[::-1], TODAY)


@given(
    st.lists(
        st.builds(
            make_event,
            id=st.text(min_size=1, max_size=5),
            title=st.text(max_size=300),
            urgency=st.integers(min_value=0, max_value=100),
            kind=st.sampled_from(["event", "assignment", "email", "weather"]),
            due=st.none() | st.datetimes(timezones=st.just(UTC)),
        ),
        max_size=25,
    )
)
def test_template_summary_always_fits_the_summary_schema(events: list[Event]) -> None:
    summary = template_summary(events, TODAY)

    assert DailySummary.model_validate(summary.model_dump()) == summary
