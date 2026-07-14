"""INFINITO_OUTER_NETWORK_MTU: MTU of the compose stack's bridge network.

Derived from the host's default-route interface MTU so the compose bridge
never exceeds the path MTU (TLS handshakes silently drop fragments otherwise).
When no default route is readable (agent sandboxes run in a network
namespace whose /proc/net/route is empty, while /sys/class/net still shows
the host NICs), falls back to the minimum MTU across UP physical interfaces;
only if that finds nothing either does the static default from
``default.env`` apply.
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


def _min_physical_uplink_mtu(net_class: Path = Path("/sys/class/net")) -> str | None:
    """Minimum MTU across UP interfaces that have a ``device`` symlink
    (physical NICs; veth/bridge/wireguard/loopback have none). The minimum is
    the safe choice: a lower bridge MTU always passes, a higher one blackholes."""
    mtus: list[int] = []
    try:
        ifaces = sorted(net_class.iterdir())
    except OSError:
        return None
    for iface_dir in ifaces:
        if not (iface_dir / "device").exists():
            continue
        try:
            operstate = (iface_dir / "operstate").read_text()  # nocheck: cache-read
            if operstate.strip() != "up":
                continue
            mtu_text = (iface_dir / "mtu").read_text()  # nocheck: cache-read
            mtus.append(int(mtu_text.strip()))
        except (OSError, ValueError):
            continue
    if not mtus:
        return None
    return str(min(mtus))


def detect_outer_mtu() -> str | None:
    iface = _default_route_iface()
    if iface is not None:
        mtu = _iface_mtu(iface)
        if mtu:
            return mtu
    return _min_physical_uplink_mtu()


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    fallback = ctx.static.get(KEY, "")
    comment = ctx.static_comments.get(KEY, "")
    detected = detect_outer_mtu()
    value = detected or fallback
    if not value:
        return
    eb.setdefault(KEY, value, comment=comment)
