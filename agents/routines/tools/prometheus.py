"""Prometheus probe reader: from a text exposition, read ``probe_success`` and
``probe_http_status_code`` for the one series whose ``app`` label equals, or
whose ``instance`` label contains, the queried app.
"""

from __future__ import annotations

import re

_SAMPLE = re.compile(r"^(?P<name>\w+)\{(?P<labels>[^}]*)\}\s+(?P<value>[\d.eE+-]+)\s*$")
_LABEL = re.compile(r'(\w+)="([^"]*)"')


def _matches(labels: dict[str, str], app: str) -> bool:
    if labels.get("app") == app:
        return True
    instance = labels.get("instance")
    return bool(instance) and app in instance


def probe(metrics: str, app: str) -> dict:
    """Return ``{"probe_success": bool, "probe_http_status_code": int | None}``
    for the series matching ``app``; an unmatched or absent series yields a
    false success and a ``None`` status.

    Args:
        metrics: the Prometheus text exposition.
        app: the app whose series to read, matched on the ``app`` or
            ``instance`` label.
    """
    success: bool | None = None
    status: int | None = None
    for raw in metrics.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        sample = _SAMPLE.match(line)
        if sample is None or sample.group("name") not in (
            "probe_success",
            "probe_http_status_code",
        ):
            continue
        if not _matches(dict(_LABEL.findall(sample.group("labels"))), app):
            continue
        value = sample.group("value")
        if sample.group("name") == "probe_success":
            success = float(value) != 0.0
        else:
            status = int(float(value))
    return {"probe_success": bool(success), "probe_http_status_code": status}
