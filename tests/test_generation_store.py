"""GenerationStore: a per-source counter bumped on disconnect, shared by every process (0074)."""

import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from command_center.core.ports import GenerationStore
from generation_support import InMemoryGenerationStore, sqlite_generations


@pytest.fixture(params=["memory", "sqlite"])
def make(request: pytest.FixtureRequest, tmp_path: Path) -> Callable[[], GenerationStore]:
    if request.param == "memory":
        shared = InMemoryGenerationStore()
        return lambda: shared
    return lambda: sqlite_generations(tmp_path)


def test_a_source_never_bumped_is_generation_zero(make: Callable[[], GenerationStore]) -> None:
    assert make().current("canvas") == 0


def test_bump_returns_the_new_generation_and_current_agrees(
    make: Callable[[], GenerationStore],
) -> None:
    store = make()
    assert store.bump("canvas") == 1
    assert store.bump("canvas") == 2
    assert store.current("canvas") == 2


def test_generations_are_per_source_and_per_user(make: Callable[[], GenerationStore]) -> None:
    store = make()
    store.bump("canvas")
    assert store.current("gmail") == 0
    assert store.current("canvas", user_id="other") == 0
    assert store.bump("canvas", user_id="other") == 1
    assert store.current("canvas") == 1


def test_a_second_handle_on_the_same_database_sees_the_bump(tmp_path: Path) -> None:
    # The api bumps, the normalizer (another process) reads: both open the same database.
    api = sqlite_generations(tmp_path)
    normalizer = sqlite_generations(tmp_path)
    api.bump("canvas")
    assert normalizer.current("canvas") == 1


def test_concurrent_bumps_each_get_their_own_number(tmp_path: Path) -> None:
    store = sqlite_generations(tmp_path)
    store.bump("canvas")  # the row exists, so every thread takes the update path
    seen: list[int] = []
    lock = threading.Lock()

    def bump() -> None:
        value = store.bump("canvas")
        with lock:
            seen.append(value)

    threads = [threading.Thread(target=bump) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(seen) == list(range(2, 10))
    assert store.current("canvas") == 9


def test_two_first_bumps_racing_both_land(tmp_path: Path) -> None:
    store = sqlite_generations(tmp_path)
    seen: list[int] = []
    lock = threading.Lock()
    start = threading.Barrier(2)

    def bump() -> None:
        start.wait()
        value = store.bump("canvas")
        with lock:
            seen.append(value)

    threads = [threading.Thread(target=bump) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(seen) == [1, 2]
