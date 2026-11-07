"""A failing write must not put event content (titles, raw fields) into its error text or logs."""

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from builders import make_event
from command_center.storage.sqlite import create_event_store

TITLE = "fake-title-Chemistry-final-DO-NOT-LOG"
RAW_VALUE = "fake-raw-value-grade-appeal-DO-NOT-LOG"
NOON = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def failing_store_url(tmp_path: Path) -> str:
    """A database whose inserts are aborted by the database itself, after the row is bound."""
    url = f"sqlite:///{tmp_path / 'events.db'}"
    create_event_store(url).close()
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TRIGGER refuse_insert BEFORE INSERT ON events "
                "BEGIN SELECT RAISE(ABORT, 'insert refused'); END"
            )
        )
    engine.dispose()
    return url


def test_a_failed_upsert_keeps_event_content_out_of_the_error_and_the_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = create_event_store(failing_store_url(tmp_path))
    event = make_event(id="a", title=TITLE, start=NOON, raw={"note": RAW_VALUE})

    with caplog.at_level(logging.DEBUG):
        try:
            store.upsert([event])
        except DBAPIError as exc:
            error = exc
            logging.getLogger("test").exception("upsert failed")
        else:
            pytest.fail("the insert should have been refused")
    store.close()

    assert "insert refused" in str(error)
    assert TITLE not in str(error)
    assert RAW_VALUE not in str(error)
    assert TITLE not in caplog.text
    assert RAW_VALUE not in caplog.text
