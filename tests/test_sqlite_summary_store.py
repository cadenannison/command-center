"""SqliteSummaryStore: a row per user and day; latest_before is strict; bad rows read as missing."""

from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, text

from command_center.core.summary import DailySummary
from command_center.storage.sqlite_summary import SqliteSummaryStore, create_summary_store

D1 = date(2026, 11, 6)
D2 = date(2026, 11, 7)
D3 = date(2026, 11, 8)


def summary(headline: str) -> DailySummary:
    return DailySummary(headline=headline, priorities=["a"], heads_up=["b"])


def make() -> SqliteSummaryStore:
    return create_summary_store("sqlite://")


def test_get_of_a_missing_day_is_none() -> None:
    assert make().get(D1) is None


def test_put_then_get_round_trips() -> None:
    store = make()
    store.put(D1, summary("one"))
    assert store.get(D1) == summary("one")


def test_put_replaces_the_row_for_that_day() -> None:
    store = make()
    store.put(D1, summary("old"))
    store.put(D1, summary("new"))
    assert store.get(D1) == summary("new")


def test_rows_are_per_user() -> None:
    store = make()
    store.put(D1, summary("mine"))
    assert store.get(D1, user_id="other") is None
    assert store.latest_before(D3, user_id="other") is None


def test_latest_before_is_the_most_recent_earlier_day_not_the_last_written() -> None:
    store = make()
    store.put(D2, summary("later day"))
    store.put(D1, summary("earlier day, written last"))
    assert store.latest_before(D3) == summary("later day")


def test_latest_before_ignores_the_day_itself_and_later_days() -> None:
    store = make()
    store.put(D2, summary("the day itself"))
    store.put(D3, summary("a later day"))
    assert store.latest_before(D2) is None
    assert store.latest_before(D1) is None


def test_latest_before_with_nothing_stored_is_none() -> None:
    assert make().latest_before(D3) is None


def test_summaries_survive_reopening_the_database(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'sub' / 'cc.db'}"
    first = create_summary_store(url)
    first.put(D1, summary("kept"))
    first.close()
    second = create_summary_store(url)
    assert second.get(D1) == summary("kept")
    second.close()


def test_a_row_that_no_longer_parses_reads_as_missing(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'cc.db'}"
    store = create_summary_store(url)
    store.put(D1, summary("fine"))
    with create_engine(url).begin() as connection:
        connection.execute(text("UPDATE summaries SET summary = '{\"nope\": 1}'"))
    assert store.get(D1) is None
    assert store.latest_before(D3) is None
    store.close()
