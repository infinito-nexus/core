"""Diagnose CLI orchestration."""

from __future__ import annotations

import os
import socket

from cli.contributing.network.diagnose.config import DEFAULT_HOSTS, EXTRA_HOSTS_ENV
from cli.contributing.network.diagnose.format import section
from cli.contributing.network.diagnose.probes import per_host_check
from cli.contributing.network.diagnose.report import (
    has_ipv6_default_route,
    show_ca_bundle,
    show_hosts,
    show_identity,
    show_iface_routes,
    show_proxies,
    show_resolv,
)
from cli.contributing.network.diagnose.tools import ensure_tools


def resolve_hosts() -> list[str]:
    extra = os.environ.get(EXTRA_HOSTS_ENV, "").split()
    return [*DEFAULT_HOSTS, *extra]


def main() -> int:
    show_identity()
    ensure_tools()
    show_iface_routes()
    show_resolv()
    show_hosts()
    show_proxies()
    show_ca_bundle()

    hosts = resolve_hosts()
    per_host_check(hosts, socket.AF_INET, "IPv4")
    if socket.has_ipv6 and has_ipv6_default_route():
        per_host_check(hosts, socket.AF_INET6, "IPv6")
    else:
        section("IPv6")
        print("  [SKIP] no IPv6 default route on this host (bridge is IPv4-only)")
    section("done")
    return 0
