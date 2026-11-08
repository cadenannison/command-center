"""The macOS menu-bar shell. The only file that imports rumps; it holds no decisions."""

from collections.abc import Callable
from typing import Any

import rumps  # pyright: ignore[reportMissingTypeStubs]

# rumps ships no type information, so it is typed once here and nowhere else.
_rumps: Any = rumps

_LOGIN_LABEL = "Launch at login"


class RumpsMenuBar:
    """A menu-bar item with open, pair, launch-at-login and quit entries and a periodic tick."""

    def __init__(  # noqa: PLR0913 - one callback per menu entry, all keyword-only
        self,
        *,
        title: str,
        login_enabled: bool,
        on_open: Callable[[], None],
        on_pair: Callable[[], None],
        on_toggle_login: Callable[[bool], bool],
        on_tick: Callable[[], str],
        on_quit: Callable[[], None],
        tick_seconds: float,
    ) -> None:
        self._on_quit = on_quit
        self._on_tick = on_tick
        self._on_toggle_login = on_toggle_login
        self._app: Any = _rumps.App("Command Center", title=title, quit_button=None)
        self._login: Any = _rumps.MenuItem(_LOGIN_LABEL, callback=self._toggle_login)
        self._login.state = int(login_enabled)
        self._app.menu = [
            _rumps.MenuItem("Open Command Center", callback=self._call(on_open)),
            _rumps.MenuItem("Pair phone", callback=self._call(on_pair)),
            None,
            self._login,
            None,
            _rumps.MenuItem("Quit", callback=self._quit),
        ]
        self._timer: Any = _rumps.Timer(self._tick, tick_seconds)

    def set_title(self, title: str) -> None:
        """Show title in the menu bar."""
        self._app.title = title

    def run(self) -> None:
        """Block on the macOS run loop until Quit."""
        self._timer.start()
        self._app.run()

    @staticmethod
    def _call(action: Callable[[], None]) -> Callable[[Any], None]:
        def handler(_sender: Any) -> None:  # noqa: ANN401 - rumps passes its own item
            action()

        return handler

    def _tick(self, _timer: Any) -> None:  # noqa: ANN401 - rumps passes its own timer
        self.set_title(self._on_tick())

    def _toggle_login(self, sender: Any) -> None:  # noqa: ANN401 - rumps passes its own item
        enabled = self._on_toggle_login(not bool(sender.state))
        sender.state = int(enabled)

    def _quit(self, _sender: Any) -> None:  # noqa: ANN401 - rumps passes its own item
        self._on_quit()
        _rumps.quit_application()
