"""Composition root for the macOS menu-bar launcher: starts the server, shows the next deadline."""

import logging
import sys
import webbrowser
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from command_center.adapters.system_clock import SystemClock
from command_center.config import Settings
from command_center.core.ports import Clock
from command_center.desktop import launch_agent
from command_center.desktop.events_client import LocalServerClient, ServerUnavailableError
from command_center.desktop.menu_title import OFFLINE_TITLE, menu_title, next_deadline
from command_center.desktop.server_process import ServerProcess, server_command

logger = logging.getLogger("command_center.desktop")

_REFRESH_SECONDS = 60.0
_WINDOW = timedelta(days=14)
_LOGIN_PROGRAM_MODULE = "command_center.desktop.main"


def current_title(client: LocalServerClient, clock: Clock, tz: ZoneInfo) -> str:
    """The menu-bar title right now, or the offline title when the server does not answer."""
    now = clock.now()
    try:
        events = client.upcoming(now, _WINDOW)
    except ServerUnavailableError:
        return OFFLINE_TITLE
    return menu_title(next_deadline(events, now), now, tz)


def main() -> None:  # pragma: no cover - needs a macOS GUI session
    """Run the menu-bar app; refuses anywhere but macOS."""
    if sys.platform != "darwin":
        msg = "the menu-bar launcher only runs on macOS"
        raise SystemExit(msg)
    from command_center.adapters.menubar_rumps import RumpsMenuBar  # noqa: PLC0415

    settings = Settings()
    clock = SystemClock()
    tz = ZoneInfo(settings.tz)
    base_url = f"http://127.0.0.1:{settings.port}"
    client = LocalServerClient(base_url)
    log_dir = settings.data_dir
    server = ServerProcess(server_command(sys.executable, settings.port), log_dir / "server.log")
    started_here = not client.healthy()
    if started_here:
        server.start()
    program = [sys.executable, "-m", _LOGIN_PROGRAM_MODULE]
    home = Path.home()

    def toggle_login(enable: bool) -> bool:  # noqa: FBT001 - a menu check mark is a boolean
        try:
            if enable:
                launch_agent.install(home, program, log_dir)
            else:
                launch_agent.remove(home)
        except OSError:
            logger.exception("could not change the launch-at-login setting")
        return launch_agent.is_installed(home)

    def open_page(path: str) -> None:
        webbrowser.open(f"{base_url}{path}")

    def quit_app() -> None:
        if started_here:
            server.stop()

    RumpsMenuBar(
        title=OFFLINE_TITLE,
        login_enabled=launch_agent.is_installed(home),
        on_open=lambda: open_page("/"),
        on_pair=lambda: open_page("/pair"),
        on_toggle_login=toggle_login,
        on_tick=lambda: current_title(client, clock, tz),
        on_quit=quit_app,
        tick_seconds=_REFRESH_SECONDS,
    ).run()


if __name__ == "__main__":  # pragma: no cover
    main()
