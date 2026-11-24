from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import random
    from collections.abc import Mapping

RETRY_AFTER = "retry-after"
RESET_HEADERS = ("x-rate-limit-reset", "x-ratelimit-reset", "ratelimit-reset")
EPOCH_THRESHOLD = 1_000_000_000
TRANSIENT_STATUSES = frozenset({408, 425, 429})


def backoff(attempt: int, base: float, cap: float, rng: random.Random) -> float:
    window = min(cap, base * 2 ** max(attempt - 1, 0))
    return rng.uniform(0, window)


def _seconds_until(value: str, now: float) -> float:
    value = value.strip()
    if not value:
        return 0
    try:
        number = float(value)
    except ValueError:
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            moment = parsedate_to_datetime(value)
        return moment.timestamp() - now
    return number - now if number > EPOCH_THRESHOLD else number


def server_delay(headers: Mapping[str, str], now: float) -> float:
    lowered = {name.lower(): value for name, value in headers.items()}
    for name in (RETRY_AFTER, *RESET_HEADERS):
        if name in lowered:
            try:
                return max(0.0, round(_seconds_until(lowered[name], now), 3))
            except (TypeError, ValueError):
                continue
    return 0


def delay(
    attempt: int,
    headers: Mapping[str, str],
    now: float,
    base: float,
    cap: float,
    rng: random.Random,
) -> float:
    return max(backoff(attempt, base, cap, rng), server_delay(headers, now))


def transient(status: int | None) -> bool:
    return status is None or status in TRANSIENT_STATUSES or status >= 500
