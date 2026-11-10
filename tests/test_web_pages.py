"""Today, Week and Month rendered through the real router and templates."""

import re
from datetime import timedelta

import pytest

from builders import NOW, make_event
from command_center.core.summary import DailySummary
from web_rig import CSRF, WebRig, make_rig, section

ALL_PAGES = ["/", "/week", "/month", "/settings"]


@pytest.fixture
def rig() -> WebRig:
    return make_rig()


def page(rig: WebRig, path: str) -> str:
    response = rig.client.get(path)
    assert response.status_code == 200
    return response.text


def test_today_lists_the_agenda_in_time_order(rig: WebRig) -> None:
    rig.seed(
        make_event(id="late", title="Zulu late", start=NOW + timedelta(hours=5)),
        make_event(id="early", title="Alpha early", start=NOW + timedelta(hours=1)),
    )

    agenda = section(page(rig, "/"), "agenda-h")

    assert agenda.index("Alpha early") < agenda.index("Zulu late")


def test_today_shows_local_times(rig: WebRig) -> None:
    rig.seed(make_event(id="m", title="Standup", start=NOW + timedelta(hours=1)))

    assert "06:00" in section(page(rig, "/"), "agenda-h")


def test_today_needs_attention_lists_urgent_items(rig: WebRig) -> None:
    rig.seed(
        make_event(id="essay", kind="assignment", title="Essay due", due=NOW + timedelta(hours=10)),
        make_event(id="lunch", title="Lunch", start=NOW + timedelta(hours=6)),
    )

    attention = section(page(rig, "/"), "attention-h")

    assert "Essay due" in attention
    assert "Lunch" not in attention


def test_today_weather_strip_shows_weather_items_outside_the_agenda(rig: WebRig) -> None:
    rig.seed(make_event(id="w", kind="weather", source="weather", title="Sunny 61F", start=NOW))

    html = page(rig, "/")

    assert "Sunny 61F" in section(html, "weather-h")
    assert "Sunny 61F" not in section(html, "agenda-h")


def test_weather_strip_credits_open_meteo_with_a_link(rig: WebRig) -> None:
    footer = section(page(rig, "/"), "weather-h")

    assert re.search(
        r'<a href="https://open-meteo\.com/"[^>]*>Weather data by Open-Meteo\.com</a>', footer
    )


def test_today_shows_the_summary_block_when_the_container_has_one() -> None:
    summary = DailySummary(
        headline="Busy Saturday", priorities=["Finish essay"], heads_up=["Quiz Monday"]
    )
    rig = make_rig(summary=summary)
    rig.seed(make_event(id="x", start=NOW))

    first = section(page(rig, "/"), "summary-h")
    block = rig.client.post(
        "/summary/generate?date=2026-11-07", headers={"X-CSRF-Token": CSRF}
    ).text

    assert 'data-state="generating"' in first
    assert all(
        text in block
        for text in ("Busy Saturday", "Priorities: Finish essay", "Heads up: Quiz Monday")
    )


def test_today_shows_the_not_enabled_summary_card_without_a_summary_service(rig: WebRig) -> None:
    assert "The AI summary is not enabled." in section(page(rig, "/"), "summary-h")


def test_today_still_renders_when_the_summary_provider_fails() -> None:
    rig = make_rig(summary=RuntimeError("provider down"))
    rig.seed(make_event(id="x", start=NOW))

    first = page(rig, "/")
    html = rig.client.post("/summary/generate?date=2026-11-07", headers={"X-CSRF-Token": CSRF}).text

    assert 'data-state="generating"' in section(first, "summary-h")
    assert "Summary unavailable" in html
    assert "provider down" not in html + first


def test_today_escapes_titles(rig: WebRig) -> None:
    rig.seed(make_event(id="x", title="<script>alert(1)</script>", start=NOW))

    html = page(rig, "/")

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_today_does_not_link_an_unsafe_event_url(rig: WebRig) -> None:
    rig.seed(make_event(id="x", title="Bad link", start=NOW, link="javascript:alert(1)"))

    assert "javascript:" not in page(rig, "/")


def test_today_links_a_safe_event_url_safely(rig: WebRig) -> None:
    rig.seed(make_event(id="x", title="Good", start=NOW, link="https://canvas.example/x"))

    assert 'href="https://canvas.example/x" target="_blank" rel="noopener noreferrer"' in page(
        rig, "/"
    )


def test_today_date_parameter_shows_that_day(rig: WebRig) -> None:
    rig.seed(make_event(id="n", title="Next day", start=NOW + timedelta(days=1)))

    assert "Next day" in page(rig, "/?date=2026-11-08")
    assert "Next day" not in page(rig, "/")


def test_a_bad_date_parameter_is_a_422(rig: WebRig) -> None:
    assert rig.client.get("/week?date=not-a-date").status_code == 422


@pytest.mark.parametrize("path", ALL_PAGES)
def test_pages_load_nothing_from_outside(rig: WebRig, path: str) -> None:
    html = page(rig, path)

    assert re.findall(r'<script[^>]*\ssrc="([^"]+)"', html) == ["/static/vendor/htmx.min.js"]
    external = set(re.findall(r'(?:src|href)="(https?:)?//([^/"]+)', html))
    assert external <= {(("https:"), "open-meteo.com")}
    assert "@import" not in html
    assert "<link" not in html


@pytest.mark.parametrize("path", ALL_PAGES)
def test_pages_are_responsive_and_not_cached(rig: WebRig, path: str) -> None:
    response = rig.client.get(path)

    assert 'name="viewport" content="width=device-width, initial-scale=1"' in response.text
    assert "@media (max-width" in response.text
    assert response.headers["cache-control"] == "no-store"


def test_week_has_seven_day_columns_with_the_load_of_each(rig: WebRig) -> None:
    rig.seed(
        make_event(id="essay", kind="assignment", due=NOW + timedelta(hours=10)),  # 90
        make_event(id="sync", start=NOW + timedelta(hours=1)),  # 60
    )

    html = page(rig, "/week")

    assert html.count('class="day-col') == 7
    saturday = re.search(r'<section class="day-col today".*?</section>', html, flags=re.DOTALL)
    assert saturday is not None
    assert '<span class="badge" title="Load: sum of urgency">150</span>' in saturday.group(0)


def test_week_navigation_moves_by_whole_weeks(rig: WebRig) -> None:
    html = page(rig, "/week?date=2026-11-16")

    assert "Week of Mon 16 Nov" in html
    assert 'href="/week?date=2026-11-09"' in html
    assert 'href="/week?date=2026-11-23"' in html


def test_month_heats_the_busy_day_and_leaves_empty_days_cold(rig: WebRig) -> None:
    rig.seed(make_event(id="m", start=NOW + timedelta(hours=1)))

    html = page(rig, "/month")

    assert re.search(r'data-level="4" href="/\?date=2026-11-07"', html)
    assert re.search(r'data-level="0" href="/\?date=2026-11-09"', html)


def test_month_lists_the_top_deadlines_most_urgent_first(rig: WebRig) -> None:
    rig.seed(
        make_event(id="a", kind="assignment", title="Later paper", due=NOW + timedelta(days=5)),
        make_event(id="b", kind="assignment", title="Tonight lab", due=NOW + timedelta(hours=10)),
        make_event(id="c", kind="assignment", title="Done thing", due=NOW, status="done"),
    )

    deadlines = section(page(rig, "/month"), "deadlines-h")

    assert deadlines.index("Tonight lab") < deadlines.index("Later paper")
    assert "Done thing" not in deadlines


def test_month_navigation_crosses_the_year(rig: WebRig) -> None:
    html = page(rig, "/month?date=2026-12-15")

    assert "December 2026" in html
    assert 'href="/month?date=2026-11-30"' in html
    assert 'href="/month?date=2027-01-01"' in html
