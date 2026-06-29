"""Per-system info dumps: identity, interfaces+MTU, /etc/resolv.conf, /etc/hosts, proxies, CA bundles."""

from __future__ import annotations

import os
import socket
import sys
import time
from pathlib import Path

from cli.contributing.network.diagnose.config import (
    CA_BUNDLE_CANDIDATES,
    PROXY_ENV_KEYS,
)
from cli.contributing.network.diagnose.format import cmd_capture, line, section


def show_identity() -> None:
    section("identity")
    line("timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    line("hostname", socket.gethostname())
    line("fqdn", socket.getfqdn())
    line("python", sys.version.split()[0])


def show_resolv() -> None:
    section("/etc/resolv.conf")
    try:
        content = Path("/etc/resolv.conf").read_text()  # nocheck: cache-read
    except OSError as e:
        print(f"  unreadable: {e}")
        return
    print(content.rstrip())


def show_hosts() -> None:
    section("/etc/hosts")
    try:
        content = Path("/etc/hosts").read_text()  # nocheck: cache-read
    except OSError as e:
        print(f"  unreadable: {e}")
        return
    print(content.rstrip())


def show_iface_routes() -> None:
    section("interfaces + MTU")
    sys_net = Path("/sys/class/net")
    if sys_net.is_dir():
        for iface in sorted(p.name for p in sys_net.iterdir()):
            mtu_path = sys_net / iface / "mtu"
            try:
                mtu = mtu_path.read_text().strip()  # nocheck: cache-read
            except OSError:
                mtu = "?"
            line(iface, f"mtu={mtu}")
    rc, out = cmd_capture(["ip", "route"])
    if rc == 0 and out.strip():
        print("\n>>> ip route")
        print(out.rstrip())
        return

    proc_route = Path("/proc/net/route")
    if not proc_route.is_file():
        return
    print("\n>>> /proc/net/route (default route only)")
    route_text = proc_route.read_text()  # nocheck: cache-read
    for raw in route_text.splitlines()[1:]:
        parts = raw.split()
        if len(parts) >= 8 and parts[1] == "00000000":
            gw_hex = parts[2]
            gw_ip = ".".join(str(int(gw_hex[i : i + 2], 16)) for i in (6, 4, 2, 0))
            print(f"  default via {gw_ip} dev {parts[0]}")
            return


def show_proxies() -> None:
    section("proxy env vars")
    for key in PROXY_ENV_KEYS:
        line(key, os.environ.get(key, "<unset>"))


def show_ca_bundle() -> None:
    section("CA bundle summary")
    for candidate in CA_BUNDLE_CANDIDATES:
        p = Path(candidate)
        if not p.is_file():
            line(candidate, "<missing>")
            continue
        try:
            size = p.stat().st_size
            content = p.read_text(errors="ignore")  # nocheck: cache-read
            count = content.count("BEGIN CERTIFICATE")
            line(candidate, f"{size}B, {count} certs")
        except OSError as e:
            line(candidate, f"unreadable: {e}")


def has_ipv6_default_route() -> bool:
    """True when an IPv6 default route exists on a non-loopback interface."""
    rc, out = cmd_capture(["ip", "-6", "route", "show", "default"])
    if rc == 0:
        for raw in out.splitlines():
            if "default" in raw and " dev lo" not in raw:
                return True
    try:
        v6_text = Path("/proc/net/ipv6_route").read_text()  # nocheck: cache-read
        for raw in v6_text.splitlines():
            parts = raw.split()
            if len(parts) >= 10 and parts[0] == "0" * 32 and parts[-1] != "lo":
                return True
    except OSError:
        pass  # best-effort: treat unreadable /proc/net/ipv6_route as no default route
    return False
