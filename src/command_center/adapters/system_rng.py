"""The real Rng: the operating system's random source."""

import random


class SystemRng:
    """Rng backed by `random.SystemRandom`. Retry jitter only; nothing here guards access."""

    def __init__(self) -> None:
        self._random = random.SystemRandom()

    def random(self) -> float:
        return self._random.random()
