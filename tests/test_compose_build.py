"""docker-compose.yml builds the image once, in the api service, so builds cannot race (0076).

Read as text, like test_compose_file.py. Services other than the api inherit `image` from the
shared `x-app` block, so the block itself must carry no `build`.
"""

import re
from pathlib import Path

COMPOSE = (Path(__file__).parent.parent / "docker-compose.yml").read_text()
IMAGE = "command-center:local"


def _block(start: str, end: str) -> str:
    return COMPOSE.split(start, 1)[1].split(end, 1)[0]


def test_the_shared_app_block_names_the_image_and_has_no_build() -> None:
    shared = _block("x-app: &app\n", "\nx-worker-health")
    assert f"image: {IMAGE}" in shared
    assert not re.search(r"^\s*build:", shared, flags=re.MULTILINE)


def test_the_api_service_is_the_only_one_that_builds() -> None:
    builds = re.findall(r"^\s*build:", COMPOSE, flags=re.MULTILINE)
    assert len(builds) == 1
    api_section = _block("\n  api:\n", "\n  scheduler:\n")
    assert re.search(r"^\s*build:", api_section, flags=re.MULTILINE)


def test_no_service_overrides_the_shared_image() -> None:
    images = re.findall(r"^\s*image:\s*(\S+)", COMPOSE, flags=re.MULTILINE)
    assert sorted(images) == sorted([IMAGE, "redis:7-alpine", "postgres:17-alpine"])
