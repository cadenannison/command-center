"""RedisReportStream recreates a consumer group Redis lost (restart, flush); no server needed."""

from typing import Any, cast

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from command_center.adapters.queue_redis import RedisReportStream
from command_center.core.jobs import SyncReport
from fakes import FakeClock
from queue_support import START
from worker_support import events, make_report

GROUP = "normalizers"


class ClientThatLosesItsGroup:
    """Answers like Redis after a flush: the first call says NOGROUP, then a report is there."""

    def __init__(self, report: SyncReport) -> None:
        self._report = report
        self.groups_created = 0
        self.reads = 0
        self._lost = True

    async def xgroup_create(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401, ARG002
        self.groups_created += 1

    async def xautoclaim(self, *args: Any, **kwargs: Any) -> list[Any]:  # noqa: ANN401, ARG002
        if self._lost:
            self._lost = False
            msg = "NOGROUP No such key or consumer group"
            raise ResponseError(msg)
        return ["0-0", []]

    async def xreadgroup(self, *args: Any, **kwargs: Any) -> list[Any]:  # noqa: ANN401, ARG002
        self.reads += 1
        fields = {"report": self._report.model_dump_json()}
        return [["stream", [("1-0", fields)]]]


async def test_a_lost_consumer_group_is_recreated_and_the_report_is_still_delivered() -> None:
    report = make_report(items=events("a"))
    client = ClientThatLosesItsGroup(report)
    stream = RedisReportStream(cast("Redis", client), FakeClock(START), prefix="cc-test")

    assert await stream.consume(GROUP, "c1", 0) == report
    assert client.groups_created == 2
