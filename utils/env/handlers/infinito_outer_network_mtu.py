"""INFINITO_OUTER_NETWORK_MTU: MTU of the compose stack's bridge network.

Derived from the host's default-route interface MTU so the compose bridge
never exceeds the path MTU (TLS handshakes silently drop fragments otherwise).
Falls back to the static default in ``default.env`` when detection fails
(no default route, no readable ``/sys/class/net/<iface>/mtu``, …).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_OUTER_NETWORK_MTU"
STATIC_READS = (KEY,)


def _default_route_iface() -> str | None:
    proc_route = Path("/proc/net/route")
    if not proc_route.is_file():
        return None
    try:
        text = proc_route.read_text()  # nocheck: cache-read - live /proc routing
    except OSError:
        return None
    for raw in text.splitlines()[1:]:
        parts = raw.split()
        if len(parts) >= 2 and parts[1] == "00000000":
            return parts[0]
    return None


def _iface_mtu(iface: str) -> str | None:
    mtu_path = Path(f"/sys/class/net/{iface}/mtu")
    try:
        return mtu_path.read_text().strip()  # nocheck: cache-read
    except OSError:
        return None


def detect_outer_mtu() -> str | None:
    iface = _default_route_iface()
    if iface is None:
        return None
    return _iface_mtu(iface)


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    fallback = ctx.static.get(KEY, "")
    comment = ctx.static_comments.get(KEY, "")
    detected = detect_outer_mtu()
    value = detected or fallback
    if not value:
        return
    eb.setdefault(KEY, value, comment=comment)
