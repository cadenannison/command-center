"""docker-compose.yml keeps the loopback promises of decisions 0013 and 0072 (read as text)."""

import re
from pathlib import Path

COMPOSE = (Path(__file__).parent.parent / "docker-compose.yml").read_text()


def test_every_published_port_is_bound_to_loopback() -> None:
    mappings = re.findall(r'^\s+- "(\d[^"]*:\d+:\d+)"', COMPOSE, flags=re.MULTILINE)
    assert mappings, "no published port found; the api should publish one"
    assert all(mapping.startswith("127.0.0.1:") for mapping in mappings)


def test_bind_all_is_set_for_the_api_service_only() -> None:
    assert COMPOSE.count("CC_BIND_ALL") == 1
    api_section = COMPOSE.split("\n  api:\n", 1)[1].split("\n  scheduler:\n", 1)[0]
    assert 'CC_BIND_ALL: "1"' in api_section


def test_there_is_one_worker_service_per_source() -> None:
    sources = re.findall(r"--source\", \"(\w+)\"", COMPOSE)
    assert sorted(sources) == ["apple_calendar", "canvas", "gmail", "learningsuite", "weather"]


def test_no_credential_is_written_into_the_file() -> None:
    assert "POSTGRES_PASSWORD:?" in COMPOSE
    assert not re.search(r"password\s*[:=]\s*[A-Za-z0-9]", COMPOSE, flags=re.IGNORECASE)
