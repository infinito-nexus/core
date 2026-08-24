#!/usr/bin/env python3
"""Gate svc-net-tor on the node onion answering over the loopback fast path.

The host resolver short-circuits the node onion (and every app subdomain of
it) to loopback, so host-side deploy steps hit the local OpenResty without a
Tor circuit. urllib is used because libcurl refuses to resolve .onion without
a proxy (RFC 7686).

Reachability over the real Tor network is gated where it blocks something:
test-e2e-playwright's wait_onion_reachable.sh, which recreates Tor for fresh
circuits between passes.

Exit 0 when the onion answers; otherwise exit non-zero so the Ansible retry
loop keeps waiting.

Usage: onion_self_reach.py <node_onion>
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request

_REACHED_ON_CLOSE = ("closed connection", "RemoteDisconnected", "Connection refused")


def check_internal(onion: str) -> str | None:
    try:
        urllib.request.urlopen(f"http://{onion}/", timeout=15)
    except urllib.error.HTTPError:
        return None
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        if any(token in detail for token in _REACHED_ON_CLOSE):
            return None
        return f"internal (loopback fast path): {detail}"
    return None


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        sys.exit("usage: onion_self_reach.py <node_onion>")
    error = check_internal(argv[1])
    if error:
        sys.exit(error)


if __name__ == "__main__":
    main(sys.argv)
