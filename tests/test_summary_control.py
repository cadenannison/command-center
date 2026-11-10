"""SummaryControl: the stored opt-in and provider choice, with the environment as the default."""

import pytest

from builders import NOW
from command_center.services.agenda import AgendaService
from command_center.services.errors import UnknownSummaryProviderError
from command_center.services.summary import SummaryService
from command_center.services.summary_control import PROVIDER_KEY, SummaryControl
from fakes import (
    FakeClock,
    FakeSummaryProvider,
    InMemoryAppSettingStore,
    InMemoryEventStore,
    InMemorySummaryStore,
)
from summary_card_support import GOOD
from web_rig import DENVER


class Builds:
    def __init__(self) -> None:
        self.names: list[str] = []

    def __call__(self, name: str) -> SummaryService:
        self.names.append(name)
        clock = FakeClock(NOW)
        agenda = AgendaService(InMemoryEventStore(), clock, DENVER)
        return SummaryService(
            agenda, InMemorySummaryStore(), FakeSummaryProvider(GOOD), clock, DENVER
        )


def make_control(
    *, enabled: bool = False, provider: str = "gemini"
) -> tuple[SummaryControl, InMemoryAppSettingStore, Builds]:
    store = InMemoryAppSettingStore()
    builds = Builds()
    control = SummaryControl(store, builds, default_enabled=enabled, default_provider=provider)
    return control, store, builds


@pytest.mark.parametrize("default", [True, False])
async def test_the_environment_value_is_the_default_until_the_user_chooses(
    *, default: bool
) -> None:
    control, _, _ = make_control(enabled=default)

    assert await control.enabled() is default


@pytest.mark.parametrize("default", [True, False])
async def test_a_stored_choice_overrides_the_environment_default(*, default: bool) -> None:
    control, _, _ = make_control(enabled=default)

    await control.set_enabled(enabled=not default)

    assert await control.enabled() is (not default)


async def test_a_garbled_stored_switch_counts_as_off() -> None:
    control, store, _ = make_control(enabled=True)
    store.set("summary.enabled", "maybe")

    assert await control.enabled() is False


async def test_nothing_is_built_while_summaries_are_off() -> None:
    control, _, builds = make_control(enabled=False)

    assert await control.service() is None
    assert builds.names == []


async def test_a_summary_switched_off_after_use_stops_returning_a_service() -> None:
    control, _, _ = make_control(enabled=True)
    assert await control.service() is not None

    await control.set_enabled(enabled=False)

    assert await control.service() is None


async def test_the_service_is_built_once_per_provider_and_reused() -> None:
    control, _, builds = make_control(enabled=True)

    first = await control.service()
    second = await control.service()

    assert first is second
    assert builds.names == ["gemini"]


async def test_choosing_another_provider_builds_that_provider() -> None:
    control, _, builds = make_control(enabled=True)
    await control.service()

    await control.set_provider("ollama")
    await control.service()

    assert builds.names == ["gemini", "ollama"]


async def test_an_unknown_provider_is_refused_and_nothing_is_stored() -> None:
    control, store, _ = make_control()

    with pytest.raises(UnknownSummaryProviderError):
        await control.set_provider("openai")

    assert store.get(PROVIDER_KEY) is None


async def test_a_stored_provider_that_is_no_longer_supported_falls_back_to_the_default() -> None:
    control, store, _ = make_control(provider="ollama")
    store.set(PROVIDER_KEY, "retired")

    assert await control.provider() == "ollama"
