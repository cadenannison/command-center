"""Runtime settings from the environment (CC_ prefix). Imported by composition roots only."""

from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    @field_validator("tz")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            msg = f"Unknown timezone {value!r}; use an IANA name such as America/Denver"
            raise ValueError(msg) from None
        return value
