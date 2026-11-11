"""Per-client request budget of the anonymous assistant API.

The budget lives in this process only. It holds request times per client
address and nothing of a request's content, and a restart forgets it.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass

CLIENT_IP_HEADER = "X-Real-IP"
UNKNOWN_CLIENT = "unknown"


@dataclass(frozen=True)
class Verdict:
    """Whether one request fits the budget.

    Args:
        allowed: the request may be answered.
        retry_after: whole seconds until the client may ask again; 0 when allowed.
    """

    allowed: bool
    retry_after: int


def client_key(headers) -> str:
    """Return the client address openresty set for a request.

    openresty overwrites ``X-Real-IP`` with ``$remote_addr`` on every proxied
    location, so a client cannot pick its own budget. A request without the
    header shares one budget with every other such request.

    Args:
        headers: the request headers, any mapping of name to value.
    """
    for name, value in headers.items():
        if name.lower() == CLIENT_IP_HEADER.lower() and str(value).strip():
            return str(value).strip()
    return UNKNOWN_CLIENT


class RateLimiter:
    """A sliding window of ``limit`` requests per ``window`` seconds per client.

    Args:
        limit: requests one client may send inside one window.
        window: length of the window in seconds.
        clock: returns the current time in seconds.
    """

    def __init__(self, limit: int, window: float, clock=time.monotonic) -> None:
        if int(limit) < 1 or float(window) <= 0:
            raise ValueError("rate limit needs limit >= 1 and window > 0")
        self._limit = int(limit)
        self._window = float(window)
        self._clock = clock
        self._seen: dict[str, deque[float]] = {}
        self._swept = clock()

    def _sweep(self, now: float) -> None:
        if now - self._swept < self._window:
            return
        self._swept = now
        for key in [
            k for k, stamps in self._seen.items() if stamps[-1] <= now - self._window
        ]:
            del self._seen[key]

    def check(self, key: str) -> Verdict:
        """Count one request of *key* and say whether it fits the budget.

        Args:
            key: the client the request is counted against.
        """
        now = self._clock()
        self._sweep(now)
        stamps = self._seen.setdefault(key, deque())
        while stamps and stamps[0] <= now - self._window:
            stamps.popleft()
        if len(stamps) >= self._limit:
            return Verdict(False, max(1, math.ceil(stamps[0] + self._window - now)))
        stamps.append(now)
        return Verdict(True, 0)

    def clients(self) -> int:
        """Return how many clients the limiter currently remembers."""
        return len(self._seen)
