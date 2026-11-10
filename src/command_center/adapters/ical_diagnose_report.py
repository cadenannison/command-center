"""The counts-only report of one feed, its conclusion line and its text (see ical_diagnose)."""

from dataclasses import dataclass
from datetime import date

from command_center.core.windows import TimeWindow


@dataclass(frozen=True, slots=True)
class FeedReport:
    """What one feed holds. `problem` is a fixed phrase when the feed could not be read."""

    number: int
    problem: str | None = None
    status_class: str | None = None
    content_kind: str | None = None
    size_bytes: int | None = None
    events: int = 0
    todos: int = 0
    dated: int = 0
    earliest: date | None = None
    latest: date | None = None
    inside: int = 0
    before: int = 0
    after: int = 0
    undated: int = 0
    cancelled: int = 0
    dropped: int = 0
    todos_dated: int = 0
    todos_inside: int = 0


def conclusion(reports: list[FeedReport]) -> str:
    """One plain-language line that says why the sync can return nothing, or that it should not."""
    blocked = _blocked(reports)
    if blocked is not None:
        return blocked
    events = sum(report.events for report in reports)
    todos = sum(report.todos for report in reports)
    if events == 0 and todos == 0:
        return "feed contains no VEVENT or VTODO"
    if events == 0:
        return "feed contains only VTODO items: the sync reads VEVENT only, so it returns 0"
    inside = sum(report.inside for report in reports)
    if inside:
        return f"{inside} events fall inside the window: a sync should return them"
    return _all_outside(reports, events)


def _blocked(reports: list[FeedReport]) -> str | None:
    """The conclusions where a sync fails outright, so event counts do not matter."""
    if not reports:
        return "no feed URLs are stored: connect LearningSuite in Settings first"
    unreadable = [report for report in reports if report.problem is not None]
    if unreadable:
        return (
            f"{len(unreadable)} of {len(reports)} feeds could not be read: "
            "fix those first (the sync fails and keeps nothing from a feed that fails)"
        )
    dropped = sum(report.dropped for report in reports)
    if dropped:
        return (
            f"some recurring events could not be expanded ({dropped}): "
            "a sync fails on them and keeps nothing from that feed"
        )
    return None


def _all_outside(reports: list[FeedReport], events: int) -> str:
    before = sum(report.before for report in reports)
    after = sum(report.after for report in reports)
    undated = sum(report.undated for report in reports)
    cancelled = sum(report.cancelled for report in reports)
    if before + after == events:
        side = "before" if after == 0 else "after" if before == 0 else "outside"
        if side == "outside":
            return "all events are outside the window (some before it, some after it)"
        return f"all events are {side} the window"
    if undated == events:
        return "all events have no start time, so none can be placed in the window"
    if cancelled == events:
        return "all events are cancelled"
    return "no event is inside the window (outside it, undated or cancelled)"


def render(reports: list[FeedReport], window: TimeWindow) -> str:
    """The text the command prints: counts, categories and dates only."""
    span = f"{window.start.date().isoformat()} to {window.end.date().isoformat()}"
    lines = [
        "LearningSuite diagnosis (counts only: no URL, title or credential is printed)",
        f"Sync window (UTC dates, the end day excluded): {span}",
        f"Feeds: {len(reports)}",
    ]
    for report in reports:
        lines.extend(_render_feed(report))
    lines.append(f"Conclusion: {conclusion(reports)}")
    return "\n".join(lines)


def _render_feed(report: FeedReport) -> list[str]:
    size = "unknown" if report.size_bytes is None else f"{report.size_bytes} bytes"
    head = (
        f"Feed {report.number}: HTTP {report.status_class or 'none'}, "
        f"content-type {report.content_kind or 'unknown'}, size {size}"
    )
    lines = [head]
    if report.problem is not None:
        lines.append(f"  Problem: {report.problem}")
        return lines
    span = (
        f"{report.earliest.isoformat()} to {report.latest.isoformat()}"
        if report.earliest and report.latest
        else "none"
    )
    buckets = (
        f"  Events: {report.inside} inside the window, {report.before} before it, "
        f"{report.after} after it, {report.undated} undated, {report.cancelled} cancelled, "
        f"{report.dropped} dropped (recurrence errors)"
    )
    todos = (
        f"  VTODO (the sync does not read them): {report.todos_dated} with a due or start, "
        f"{report.todos_inside} inside the window"
    )
    counts = f"  VEVENT {report.events}, VTODO {report.todos}; with a start or due: {report.dated}"
    return [*lines, counts, f"  Dates (start or due): {span}", buckets, todos]
