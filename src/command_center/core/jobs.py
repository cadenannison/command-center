"""Background job model: a unit of work for a JobQueue and the record of one that gave up."""

from typing import Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

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

    def next_attempt(self) -> Self:
        """Return a copy with attempt + 1."""
        return self.model_copy(update={"attempt": self.attempt + 1})


class DeadLetter(BaseModel):
    """A job that exhausted its retries, with why and when."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    job: Job
    reason: str
    failed_at: AwareDatetime
