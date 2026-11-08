"""The workers' command line: exactly one role, and the file backend reaches the app root."""

from pathlib import Path

import pytest

from command_center.app import build_app
from command_center.config import Settings
from command_center.workers.__main__ import parse_args, source_prefix


def test_source_role_names_the_source() -> None:
    args = parse_args(["--source", "canvas"])
    assert (args.source, args.normalizer, args.scheduler) == ("canvas", False, False)


def test_normalizer_and_scheduler_roles() -> None:
    assert parse_args(["--normalizer"]).normalizer is True
    assert parse_args(["--scheduler"]).scheduler is True


@pytest.mark.parametrize(
    "argv", [[], ["--normalizer", "--scheduler"], ["--source", "a", "--normalizer"]]
)
def test_exactly_one_role_is_required(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        parse_args(argv)


def test_the_heartbeat_file_is_optional() -> None:
    assert parse_args(["--normalizer"]).heartbeat_file is None
    args = parse_args(["--normalizer", "--heartbeat-file", "beat"])
    assert args.heartbeat_file == Path("beat")


def test_each_source_has_its_own_queue_prefix() -> None:
    assert source_prefix("canvas") != source_prefix("gmail")
    assert source_prefix("canvas") == "cc-canvas"


def test_distributed_mode_leaves_scheduling_to_the_scheduler_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[int | None] = []

    def fake_create(_container: object, **kwargs: object) -> object:
        seen.append(kwargs["sync_interval_minutes"])  # type: ignore[arg-type]
        return object()

    monkeypatch.setattr("command_center.app.create_api_app", fake_create)
    monkeypatch.setenv("CC_DATABASE_URL", f"sqlite:///{tmp_path / 'a.db'}")
    monkeypatch.setenv("CC_REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("CC_MODE", "distributed")
    build_app(Settings(_env_file=None))  # type: ignore[call-arg]
    monkeypatch.setenv("CC_MODE", "single")
    build_app(Settings(_env_file=None))  # type: ignore[call-arg]
    assert seen == [None, 30]
