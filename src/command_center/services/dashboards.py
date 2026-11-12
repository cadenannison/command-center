"""Dashboards and display settings behind /v1 (decisions 0355 to 0358).

Handlers call one method each. The stores are synchronous and small, like the other setting
stores, so they are called directly. Every write names the revision it was based on.
"""

from collections.abc import Sequence

from command_center.core.dashboards import (
    Dashboard,
    DashboardInput,
    DashboardNotFoundError,
    DisplayInput,
    DisplaySettings,
)
from command_center.core.ports import Clock, DashboardStore, DisplaySettingsStore, IdSource

__all__ = ["DashboardNotFoundError", "DashboardService"]


class DashboardService:
    """List, create, read, replace, delete and reorder dashboards; read and replace display."""

    def __init__(
        self,
        dashboards: DashboardStore,
        display: DisplaySettingsStore,
        clock: Clock,
        ids: IdSource,
    ) -> None:
        self._dashboards = dashboards
        self._display = display
        self._clock = clock
        self._ids = ids

    async def list_all(self) -> list[Dashboard]:
        """Every dashboard in position order."""
        return self._dashboards.list_all()

    async def get(self, dashboard_id: str) -> Dashboard:
        """One dashboard; raises DashboardNotFoundError."""
        found = self._dashboards.get(dashboard_id)
        if found is None:
            raise DashboardNotFoundError
        return found

    async def add(self, body: DashboardInput) -> Dashboard:
        """Add a dashboard in the last position; raises DashboardLimitError at the cap."""
        return self._dashboards.add(self._ids.new_id(), body.name, body.layout, self._clock.now())

    async def replace(self, dashboard_id: str, revision: int, body: DashboardInput) -> Dashboard:
        """Replace name and layout if the stored revision is `revision`."""
        return self._dashboards.replace(
            dashboard_id, revision, body.name, body.layout, self._clock.now()
        )

    async def delete(self, dashboard_id: str, revision: int) -> None:
        """Delete if the stored revision is `revision`."""
        self._dashboards.delete(dashboard_id, revision)

    async def reorder(self, ids: Sequence[str]) -> list[Dashboard]:
        """Reorder; `ids` must be every dashboard exactly once."""
        return self._dashboards.reorder(ids)

    async def display(self) -> DisplaySettings:
        """The stored display settings, or the defaults at revision 0."""
        return self._display.get()

    async def replace_display(self, revision: int, body: DisplayInput) -> DisplaySettings:
        """Replace the display settings if the stored revision is `revision`."""
        return self._display.replace(
            DisplaySettings(**body.model_dump()), revision, self._clock.now()
        )
