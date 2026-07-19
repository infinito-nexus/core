"""Render the timeout-hardened curl base command (SPOT).

    {{ 30 | curl }}                      -> curl -s --connect-timeout 5 --max-time 30
    {{ 300 | curl }}                     -> curl -s --connect-timeout 5 --max-time 300
    {{ lookup('timeout', 30) | curl }}   -> TIMEOUT_FACTOR-scaled variant

Args:
    max_time: Seconds for the whole transfer; without it curl hangs forever
        on an accepted-but-silent peer and task retries never fire.
    connect_timeout: Seconds curl waits for the TCP/TLS connect (default 5).

Callers append their own flags (``-S``, ``-f``, ``-o``, ...) after the filter.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleFilterError


def curl(max_time: Any, connect_timeout: Any = 5) -> str:
    try:
        max_time_val = int(max_time)
        connect_timeout_val = int(connect_timeout)
    except (TypeError, ValueError) as exc:
        raise AnsibleFilterError(
            f"curl filter: max_time {max_time!r} / connect_timeout "
            f"{connect_timeout!r} must be integers (seconds)"
        ) from exc
    if max_time_val <= 0 or connect_timeout_val <= 0:
        raise AnsibleFilterError(
            f"curl filter: max_time {max_time_val} and connect_timeout "
            f"{connect_timeout_val} must be > 0"
        )
    return f"curl -s --connect-timeout {connect_timeout_val} --max-time {max_time_val}"


class FilterModule:
    def filters(self):
        return {
            "curl": curl,
        }
