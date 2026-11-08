"""The five sources, built once for every composition root that needs them."""

from zoneinfo import ZoneInfo

from command_center.adapters.caldav_apple import AppleCalendarAdapter
from command_center.adapters.canvas import CanvasAdapter
from command_center.adapters.gmail import GmailAdapter
from command_center.adapters.ical_feed import IcalFeedAdapter
from command_center.adapters.weather import WeatherAdapter
from command_center.core.ports import Clock, SourceAdapter


def build_source_adapters(tz: ZoneInfo, clock: Clock) -> dict[str, SourceAdapter]:
    """The five sources, keyed by the name each reports."""
    adapters: list[SourceAdapter] = [
        CanvasAdapter(clock),
        AppleCalendarAdapter(tz, clock),
        IcalFeedAdapter(tz, clock),
        GmailAdapter(clock),
        WeatherAdapter(clock),
    ]
    return {adapter.name: adapter for adapter in adapters}
