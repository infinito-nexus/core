"""Filter ``loki_retention``: turn the per-class retention map into Loki limits."""

from __future__ import annotations

import re

from ansible.errors import AnsibleFilterError

_DURATION = re.compile(r"^(?P<amount>[1-9][0-9]*)(?P<unit>[hdw])$")
_CLASS = re.compile(r"^[a-z][a-z0-9_]*$")
_HOURS_PER_UNIT = {"h": 1, "d": 24, "w": 168}
MINIMUM_HOURS = 24


def _hours(log_class: str, duration: object) -> int:
    match = _DURATION.match(str(duration).strip())
    if match is None:
        raise AnsibleFilterError(
            f"loki_retention: retention of log class {log_class!r} is "
            f"{duration!r}; expected <n>h, <n>d or <n>w"
        )
    hours = int(match.group("amount")) * _HOURS_PER_UNIT[match.group("unit")]
    if hours < MINIMUM_HOURS:
        raise AnsibleFilterError(
            f"loki_retention: retention of log class {log_class!r} is {hours}h; "
            f"the compactor deletes in {MINIMUM_HOURS}h index periods, so it "
            f"must be at least {MINIMUM_HOURS}h"
        )
    return hours


def loki_retention(classes: dict, label: str) -> dict:
    """Build ``limits_config`` retention values from a class map.

    Args:
        classes: mapping of log class to retention, e.g. ``{"system": "7d"}``.
        label: stream label that carries the log class.

    Returns:
        ``{"period": "<h>h", "streams": [...]}``: ``period`` is the longest
        class retention, the global fallback for a stream without a class;
        ``streams`` holds one ``{selector, priority, period}`` entry per class
        in class-name order.

    Raises:
        AnsibleFilterError: the map is empty, a class name is not a label
            value Loki can select on, or a retention is malformed or shorter
            than one index period.
    """
    if not isinstance(classes, dict) or not classes:
        raise AnsibleFilterError(
            "loki_retention: the retention map must name at least one log class"
        )
    if not _CLASS.match(str(label)):
        raise AnsibleFilterError(f"loki_retention: invalid stream label {label!r}")
    streams = []
    for log_class in sorted(classes):
        if not _CLASS.match(str(log_class)):
            raise AnsibleFilterError(
                f"loki_retention: invalid log class name {log_class!r}"
            )
        hours = _hours(log_class, classes[log_class])
        streams.append(
            {
                "selector": f'{{{label}="{log_class}"}}',
                "priority": 1,
                "period": f"{hours}h",
            }
        )
    longest = max(int(stream["period"][:-1]) for stream in streams)
    return {"period": f"{longest}h", "streams": streams}


class FilterModule:
    def filters(self):
        return {"loki_retention": loki_retention}
