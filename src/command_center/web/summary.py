"""The optional AI summary block. The web only asks for text; opt-in lives in the service."""

import logging
from dataclasses import dataclass
from datetime import date

from command_center.services.container import Container

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SummaryBlock:
    """The summary block of the Today page; `text` is None when the summary failed."""

    text: str | None


async def load_summary(container: Container, day: date) -> SummaryBlock | None:
    """The block to show, or None when summaries are off (no service) or there is nothing."""
    if container.summary is None:
        return None
    try:
        text = await container.summary.for_day(day)
    except Exception as exc:  # noqa: BLE001  a summary failure must not take the dashboard down
        logger.warning("Summary unavailable: %s", type(exc).__name__)
        return SummaryBlock(text=None)
    return SummaryBlock(text=text) if text else None
