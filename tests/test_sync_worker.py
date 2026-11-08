"""SyncWorker: one job in, one report out, and the right fate for every kind of failure."""

import json
import logging
from datetime import timedelta

import pytest

from command_center.adapters.inprocess_queue import InProcessQueue
from command_center.adapters.inprocess_reports import InProcessReportStream
from command_center.adapters.json_log import JsonFormatter
from command_center.core.errors import AuthExpired, FatalError, TransientError
from command_center.core.jobs import SyncReport
from command_center.workers.sync_worker import SyncWorker
from fake_adapter import FetchStep
from fakes import FakeClock, InMemorySecretStore
from queue_support import POLICY, START, SeededRng, make_job
from worker_support import (
    BREAKER_FAILURES,
    COOL_DOWN,
    LONG_ENOUGH,
    VISIBILITY,
    adapter_with,
    events,
    make_worker,
)

SECRET_TEXT = "token fake-token-1234 rejected for ann@example.com"  # noqa: S105


class Rig:
    def __init__(self) -> None:
        self.clock = FakeClock(START)
        self.queue = InProcessQueue(
            self.clock, SeededRng(), policy=POLICY, visibility_timeout=VISIBILITY
        )
        self.reports = InProcessReportStream(self.clock, visibility_timeout=VISIBILITY)

    async def sent(self) -> list[SyncReport]:
        found: list[SyncReport] = []
        while (report := await self.reports.consume("g", "c", 0)) is not None:
            found.append(report)
            await self.reports.ack(report)
        return found


@pytest.fixture
def rig() -> Rig:
    return Rig()


async def test_a_fetched_result_is_reported_in_full_and_the_job_is_acked(rig: Rig) -> None:
    adapter = adapter_with(events("a", "b"))
    worker = make_worker(adapter, rig.queue, rig.reports, rig.clock)
    await rig.queue.publish(make_job("j1"))

    assert await worker.run_once() is True

    [report] = await rig.sent()
    assert (report.status, [e.id for e in report.events]) == ("ok", ["a", "b"])
    assert (report.window, report.correlation_id) == (make_job("j1").window, "corr-j1")
    rig.clock.advance(VISIBILITY * 2)
    assert await rig.queue.consume("g", "c", 0) is None


async def test_the_adapter_gets_the_credentials_from_the_store_not_from_the_job(rig: Rig) -> None:
    adapter = adapter_with(events("a"))
    worker = make_worker(adapter, rig.queue, rig.reports, rig.clock)
    await rig.queue.publish(make_job("j1"))
    await worker.run_once()
    assert adapter.fetches[0][0] == {"token": "fake-token-1234"}
    assert "fake-token-1234" not in make_job("j1").model_dump_json()


async def test_an_empty_queue_handles_nothing(rig: Rig) -> None:
    worker = make_worker(adapter_with(), rig.queue, rig.reports, rig.clock)
    assert await worker.run_once() is False


async def test_auth_expired_reports_reconnect_and_is_not_retried(rig: Rig) -> None:
    adapter = adapter_with(AuthExpired("token rejected"))
    worker = make_worker(adapter, rig.queue, rig.reports, rig.clock)
    await rig.queue.publish(make_job("j1"))
    await worker.run_once()

    [report] = await rig.sent()
    assert (report.status, report.events) == ("reconnect", ())
    rig.clock.advance(LONG_ENOUGH)
    assert await rig.queue.consume("g", "c", 0) is None
    assert await rig.queue.list_dead_letters() == []


async def test_no_stored_credentials_reports_reconnect_without_calling_the_adapter(
    rig: Rig,
) -> None:
    adapter = adapter_with(events("a"))
    worker = make_worker(adapter, rig.queue, rig.reports, rig.clock, secrets=InMemorySecretStore())
    await rig.queue.publish(make_job("j1"))
    await worker.run_once()

    [report] = await rig.sent()
    assert (report.status, report.message) == ("reconnect", "Not connected: no credentials stored")
    assert adapter.fetches == []


async def test_a_transient_failure_is_requeued_with_the_next_attempt_and_reports_nothing(
    rig: Rig,
) -> None:
    adapter = adapter_with(TransientError("timeout"), events("a"))
    worker = make_worker(adapter, rig.queue, rig.reports, rig.clock)
    await rig.queue.publish(make_job("j1"))
    await worker.run_once()
    assert await rig.sent() == []

    rig.clock.advance(LONG_ENOUGH)
    await worker.run_once()
    [report] = await rig.sent()
    assert report.status == "ok"
    assert len(adapter.fetches) == 2


async def test_a_job_that_keeps_failing_is_dead_lettered_after_the_last_attempt(rig: Rig) -> None:
    adapter = adapter_with(TransientError("timeout"))
    worker = make_worker(adapter, rig.queue, rig.reports, rig.clock)
    await rig.queue.publish(make_job("j1"))
    for _ in range(POLICY.max_attempts):
        await worker.run_once()
        rig.clock.advance(LONG_ENOUGH)

    [dead] = await rig.queue.list_dead_letters()
    assert (dead.job.attempt, dead.reason) == (POLICY.max_attempts, "TransientError")
    [report] = await rig.sent()
    assert report.status == "error"
    assert report.message.startswith("Source unreachable after 3 attempts")


async def test_a_fatal_failure_is_dead_lettered_at_once_and_reports_an_error(rig: Rig) -> None:
    adapter = adapter_with(FatalError("malformed response"))
    worker = make_worker(adapter, rig.queue, rig.reports, rig.clock)
    await rig.queue.publish(make_job("j1"))
    await worker.run_once()

    [dead] = await rig.queue.list_dead_letters()
    assert (dead.job.attempt, dead.reason) == (1, "FatalError")
    [report] = await rig.sent()
    assert (report.status, report.message) == ("error", "Sync failed: malformed response")
    assert len(adapter.fetches) == 1


async def test_a_job_for_another_source_is_dead_lettered_without_a_fetch(rig: Rig) -> None:
    adapter = adapter_with(events("a"))
    worker = make_worker(adapter, rig.queue, rig.reports, rig.clock)
    await rig.queue.publish(make_job("j1", source="gmail"))
    await worker.run_once()
    assert adapter.fetches == []
    assert [d.reason for d in await rig.queue.list_dead_letters()] == ["WrongJob"]


async def test_an_adapter_bug_is_retried_without_counting_against_the_breaker(rig: Rig) -> None:
    adapter = adapter_with(RuntimeError(SECRET_TEXT), events("a"))
    worker = make_worker(adapter, rig.queue, rig.reports, rig.clock)
    for n in range(BREAKER_FAILURES + 1):
        await rig.queue.publish(make_job(f"j{n}"))
    await worker.run_once()
    rig.clock.advance(LONG_ENOUGH)
    assert await worker.run_once() is True  # the breaker is still closed


async def test_the_breaker_opens_after_n_transient_failures_and_the_worker_stops_consuming(
    rig: Rig,
) -> None:
    adapter = adapter_with(TransientError("down"))
    worker = make_worker(adapter, rig.queue, rig.reports, rig.clock)
    for n in range(BREAKER_FAILURES):
        await rig.queue.publish(make_job(f"j{n}"))
        await worker.run_once()
    fetches = len(adapter.fetches)

    await rig.queue.publish(make_job("later"))
    assert await worker.run_once() is False
    assert len(adapter.fetches) == fetches
    assert (await rig.queue.consume("g", "other", 0)) is not None  # the job was never taken


async def _open_then_trial(rig: Rig, trial: FetchStep, after: int) -> tuple[SyncWorker, int]:
    """Open the breaker, let the cool-down pass, run one trial job; return the worker."""
    script: list[FetchStep] = [
        *[TransientError("down")] * BREAKER_FAILURES,
        trial,
        *[TransientError("down")] * after,
    ]
    adapter = adapter_with(*script, events("tail"))
    worker = make_worker(adapter, rig.queue, rig.reports, rig.clock)
    for n in range(BREAKER_FAILURES):
        await rig.queue.publish(make_job(f"j{n}"))
        await worker.run_once()
    await rig.queue.publish(make_job("trial"))
    rig.clock.advance(COOL_DOWN + timedelta(seconds=1))
    assert await worker.run_once() is True
    return worker, len(adapter.fetches)


async def _still_closed_after(rig: Rig, worker: SyncWorker, failures: int) -> bool:
    for n in range(failures):
        await rig.queue.publish(make_job(f"again{n}"))
        assert await worker.run_once() is True
    await rig.queue.publish(make_job("probe"))
    return await worker.run_once()


async def test_the_breaker_lets_one_trial_through_after_the_cool_down_and_closes_on_success(
    rig: Rig,
) -> None:
    worker, fetches = await _open_then_trial(rig, events("a"), BREAKER_FAILURES - 1)
    assert fetches == BREAKER_FAILURES + 1
    assert [r.status for r in await rig.sent()] == ["ok"]
    assert await _still_closed_after(rig, worker, BREAKER_FAILURES - 1)


@pytest.mark.parametrize("answer", [AuthExpired("no"), FatalError("bad request")])
async def test_a_source_that_answers_with_a_rejection_closes_the_breaker(
    rig: Rig, answer: Exception
) -> None:
    worker, _ = await _open_then_trial(rig, answer, BREAKER_FAILURES - 1)
    assert await _still_closed_after(rig, worker, BREAKER_FAILURES - 1)


def lines(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    formatter = JsonFormatter()
    return [json.loads(formatter.format(record)) for record in caplog.records]


async def test_logs_carry_the_error_class_and_never_the_message_or_a_credential(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    adapter = adapter_with(TransientError(SECRET_TEXT), FatalError(SECRET_TEXT))
    worker = make_worker(adapter, rig.queue, rig.reports, rig.clock)
    await rig.queue.publish(make_job("j1"))
    await worker.run_once()  # transient: will retry
    rig.clock.advance(LONG_ENOUGH)
    await worker.run_once()  # fatal: dead-lettered

    text = "\n".join(json.dumps(line) for line in lines(caplog))
    assert "fake-token-1234" not in text
    assert "ann@example.com" not in text
    classes = [line.get("error_class") for line in lines(caplog)]
    assert classes.count("TransientError") >= 1
    assert classes.count("FatalError") >= 1


async def test_giving_up_is_logged_with_the_error_class(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    worker = make_worker(adapter_with(TransientError("x")), rig.queue, rig.reports, rig.clock)
    await rig.queue.publish(make_job("j1"))
    for _ in range(POLICY.max_attempts):
        await worker.run_once()
        rig.clock.advance(LONG_ENOUGH)
    gave_up = [line for line in lines(caplog) if "gave up" in str(line["message"])]
    assert [(g["error_class"], g["attempt"]) for g in gave_up] == [("TransientError", 3)]
