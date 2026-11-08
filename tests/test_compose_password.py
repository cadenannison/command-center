"""Every use of POSTGRES_PASSWORD in docker-compose.yml is required, never defaulted (0077)."""

import re
from pathlib import Path

COMPOSE = (Path(__file__).parent.parent / "docker-compose.yml").read_text()


def test_every_interpolation_of_the_password_is_required_with_no_default() -> None:
    uses = re.findall(r"\$\{POSTGRES_PASSWORD([^}]*)\}", COMPOSE)
    assert len(uses) >= 2, "the password should reach postgres and DATABASE_URL"
    assert all(use.startswith(":?") for use in uses)


def test_the_password_is_not_read_from_a_file_in_the_repo() -> None:
    assert "env_file" not in COMPOSE
