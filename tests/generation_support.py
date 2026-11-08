"""An in-memory GenerationStore, and a helper that opens the SQLite one for a test."""

from pathlib import Path

from command_center.core.ports import GenerationStore
from command_center.storage.sqlite_generations import create_generation_store


class InMemoryGenerationStore:
    """GenerationStore in a dict; the SQLite one runs the same suite in test_generation_store."""

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], int] = {}

    def current(self, source: str, *, user_id: str = "local") -> int:
        return self.values.get((user_id, source), 0)

    def bump(self, source: str, *, user_id: str = "local") -> int:
        value = self.current(source, user_id=user_id) + 1
        self.values[(user_id, source)] = value
        return value


def sqlite_generations(tmp_path: Path, name: str = "generations.db") -> GenerationStore:
    return create_generation_store(f"sqlite:///{tmp_path / name}")
