"""Render the timeout-hardened, retry-hardened curl base command (SPOT).

    {{ 30 | curl }}                      -> curl -s --connect-timeout 5 --max-time 30 --retry 3 --retry-all-errors --retry-delay 2
    {{ 300 | curl }}                     -> curl -s --connect-timeout 5 --max-time 300 --retry 3 --retry-all-errors --retry-delay 2
    {{ lookup('timeout', 30) | curl }}   -> TIMEOUT_FACTOR-scaled variant

Args:
    max_time: Seconds for the whole transfer; without it curl hangs forever
        on an accepted-but-silent peer and task retries never fire.
    connect_timeout: Seconds curl waits for the TCP/TLS connect (default 5).
    retries: --retry count; --retry-all-errors makes it cover transport-layer
        resets (exit 35/52/56), the class that hard-fails deploys on flaky CI
        egress. Pass 0 to opt a call out of retrying.

Callers append their own flags (``-S``, ``-f``, ``-o``, ...) after the filter.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleFilterError


def curl(max_time: Any, connect_timeout: Any = 5, retries: Any = 3) -> str:
    try:
        max_time_val = int(max_time)
        connect_timeout_val = int(connect_timeout)
        retries_val = int(retries)
    except (TypeError, ValueError) as exc:
        raise AnsibleFilterError(
            f"curl filter: max_time {max_time!r} / connect_timeout "
            f"{connect_timeout!r} / retries {retries!r} must be integers"
        ) from exc
    if max_time_val <= 0 or connect_timeout_val <= 0:
        raise AnsibleFilterError(
            f"curl filter: max_time {max_time_val} and connect_timeout "
            f"{connect_timeout_val} must be > 0"
        )
    if retries_val < 0:
        raise AnsibleFilterError(f"curl filter: retries {retries_val} must be >= 0")
    base = f"curl -s --connect-timeout {connect_timeout_val} --max-time {max_time_val}"
    if retries_val:
        base += f" --retry {retries_val} --retry-all-errors --retry-delay 2"
    return base


class FilterModule:
    def filters(self):
        return {
            "curl": curl,
        }
