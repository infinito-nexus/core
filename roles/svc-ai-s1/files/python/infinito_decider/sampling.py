"""When to compare several routes instead of answering with one."""

from __future__ import annotations

import random
import time


class Sampler:
    """Whether this request is answered by several routes instead of one.

    Args:
        trigger: ``seconds`` spaces comparisons in time, ``requests`` counts
            them out, ``probability`` draws one in *interval*.
        interval: seconds, requests or odds, read according to *trigger*.
        clock: monotonic source, injected so a test does not wait.
        draw: uniform source in [0, 1), injected for the same reason.
    """

    def __init__(self, trigger, interval, clock=time.monotonic, draw=random.random):
        self._trigger = trigger
        self._interval = max(int(interval), 1)
        self._clock = clock
        self._draw = draw
        self._last = None
        self._seen = 0

    def due(self):
        """True when this request should be compared across routes."""
        if self._trigger == "requests":
            self._seen += 1
            if self._seen < self._interval:
                return False
            self._seen = 0
            return True
        if self._trigger == "probability":
            return self._draw() < 1.0 / self._interval
        now = self._clock()
        if self._last is not None and now - self._last < self._interval:
            return False
        self._last = now
        return True
