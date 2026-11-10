"""SummaryStore.delete: drop one user's summary for one day, and nothing else."""

from collections.abc import Iterator
from datetime import date

import pytest

from command_center.core.ports import SummaryStore
from command_center.core.summary import DailySummary
from command_center.storage.sqlite_summary import create_summary_store
from fakes import InMemorySummaryStore

DAY = date(2026, 11, 7)
OTHER = date(2026, 11, 8)
SUMMARY = DailySummary(headline="Busy Saturday", priorities=["Finish essay"], heads_up=[])


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest) -> Iterator[SummaryStore]:
    if request.param == "memory":
        yield InMemorySummaryStore()
        return
    sqlite = create_summary_store("sqlite:///:memory:")
    yield sqlite
    sqlite.close()


def test_a_deleted_summary_reads_as_missing(store: SummaryStore) -> None:
    store.put(DAY, SUMMARY)

    store.delete(DAY)

    assert store.get(DAY) is None


def test_deleting_one_day_keeps_the_others(store: SummaryStore) -> None:
    store.put(DAY, SUMMARY)
    store.put(OTHER, SUMMARY)

    store.delete(DAY)

    assert store.get(OTHER) == SUMMARY


def test_deleting_one_users_summary_keeps_another_users(store: SummaryStore) -> None:
    store.put(DAY, SUMMARY, user_id="a")
    store.put(DAY, SUMMARY, user_id="b")

    store.delete(DAY, user_id="a")

    assert store.get(DAY, user_id="b") == SUMMARY


def test_deleting_a_day_with_no_summary_is_not_an_error(store: SummaryStore) -> None:
    store.delete(DAY)

    assert store.get(DAY) is None
