"""Background job model: a unit of work for a JobQueue and the record of one that gave up."""

from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from command_center.core.schema import Event
from command_center.core.windows import TimeWindow

MAX_REASON_LENGTH = 300
VISIBILITY_TIMEOUT_REASON = "visibility timeout expired on the last attempt"


class Job(BaseModel):
    """One unit of work; `attempt` is the 1-based number of the current processing attempt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    source: str = Field(min_length=1)
    window: TimeWindow
    attempt: int = Field(default=1, ge=1)
    correlation_id: str = Field(min_length=1)
    # The source's generation when the job was queued: a disconnect bumps it, which makes the
    # normalizer drop whatever this job produces afterwards (decision 0074).
    generation: int = Field(default=0, ge=0)

    def next_attempt(self) -> Self:
        """Return a copy with attempt + 1."""
        return self.model_copy(update={"attempt": self.attempt + 1})


class DeadLetter(BaseModel):
    """A job that exhausted its retries, with why and when."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    job: Job
    reason: str
    failed_at: AwareDatetime


class SyncReport(BaseModel):
    """What a sync worker tells the normalizer: the fetched events, or why there are none.

    `ok` carries every event the fetch returned for `window` (a full result, never partial, so
    `EventStore.replace` may delete what is missing). `reconnect` and `error` carry no events:
    stored events stay as they were, only the source's state changes. Never carries credentials.
    `generation` is the one of the job that produced it: a report older than the source's current
    generation is dropped, never applied.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    window: TimeWindow
    status: Literal["ok", "reconnect", "error"]
    message: str
    at: AwareDatetime
    events: tuple[Event, ...] = ()
    generation: int = Field(default=0, ge=0)  # copied from the job; see Job.generation

    @model_validator(mode="after")
    def _only_ok_carries_events(self) -> Self:
        if self.status != "ok" and self.events:
            msg = f"a {self.status} report carries no events"
            raise ValueError(msg)
        return self


class DeadReport(BaseModel):
    """A report the normalizer gave up on. Holds no events: they may be large and personal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    correlation_id: str
    source: str
    reason: str
    failed_at: AwareDatetime
