"""Runtime settings from the environment (CC_ prefix). Imported by composition roots only."""

import re
from pathlib import Path
from typing import Annotated, Any, Literal, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_PLAIN_HOSTNAME = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*")
# Loopback is always served and needs no token; 0.0.0.0 is not a name a Host header may carry.
_NEVER_LISTED = frozenset({"localhost", "127.0.0.1", "0.0.0.0"})  # noqa: S104 - compared, never bound


def _default_database_url(data: dict[str, Any]) -> str:
    data_dir: Path = data["data_dir"]
    return f"sqlite:///{data_dir / 'command_center.db'}"


class Settings(BaseSettings):
    """Immutable settings. `DATABASE_URL` is also read (without the prefix) for hosted databases."""

    model_config = SettingsConfigDict(
        env_prefix="CC_",
        frozen=True,
        extra="ignore",
        populate_by_name=True,
    )

    # Loopback only (AGENTS.md rule 5); widening this is a security decision, not a setting.
    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    data_dir: Path = Field(default_factory=lambda: Path.home() / ".command-center")
    # Declared after data_dir: its default is derived from it.
    database_url: str = Field(
        default_factory=_default_database_url,
        repr=False,  # a hosted URL embeds the password; keep it out of repr/str and logs
        validation_alias=AliasChoices("CC_DATABASE_URL", "DATABASE_URL"),
    )
    tz: str = "America/Denver"
    sync_interval_minutes: int = Field(default=30, ge=1)
    # AI summaries are opt-in (decision 0004). Off means no provider is built and nothing leaves.
    summary_enabled: bool = False
    summary_provider: Literal["gemini", "ollama"] = "gemini"
    # None lets the chosen provider's adapter apply its own default model.
    summary_model: str | None = None
    summary_include_email: bool = False
    # Hosts other than loopback that may reach the API (the tailnet name Tailscale Serve answers
    # on). Each one needs a device token (decision 0057). Comma separated in CC_ALLOWED_HOSTS.
    allowed_hosts: Annotated[tuple[str, ...], NoDecode] = ()

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def _plain_hostnames(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.split(",")
        if not isinstance(value, (list, tuple)):
            return value
        hosts: list[str] = []
        for item in cast("list[object] | tuple[object, ...]", value):
            if not isinstance(item, str) or not item.strip():
                continue
            host = item.strip().lower()
            if not _PLAIN_HOSTNAME.fullmatch(host) or host in _NEVER_LISTED:
                msg = (
                    "allowed_hosts takes plain tailnet hostnames such as mac.tail1234.ts.net: "
                    "no scheme, port, path, wildcard or loopback name"
                )
                raise ValueError(msg)
            hosts.append(host)
        return tuple(hosts)

    @field_validator("tz")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            msg = f"Unknown timezone {value!r}; use an IANA name such as America/Denver"
            raise ValueError(msg) from None
        return value
