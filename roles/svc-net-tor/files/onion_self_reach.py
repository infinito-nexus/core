#!/usr/bin/env python3
"""Gate svc-net-tor on the node onion being reachable on BOTH paths the
deployment relies on:

  * internal  — the host resolver short-circuits the node onion (and every app
                subdomain of it) to loopback, so host-side deploy steps hit the
                local OpenResty without a Tor circuit. urllib is used because
                libcurl refuses to resolve .onion without a proxy (RFC 7686).
  * external  — the real Tor network via the node SOCKS proxy; only reachable
                once the hidden-service descriptor is (re)published (~2-5 min
                after a Tor restart). This is the path Playwright / real users
                take, so it must actually work end to end.

Exit 0 only when both succeed; otherwise exit non-zero with a message naming
the failing path so the Ansible retry loop keeps waiting.

Usage: onion_self_reach.py <node_onion> <socks_host:port>
"""

from __future__ import annotations

import subprocess
import sys
import urllib.error
import urllib.request

# Any HTTP status — or a connection close / refusal from the local endpoint —
# proves the path works; only resolution/timeout failures mean "not ready".
# "Connection refused" is reached-ness for the loopback fast path: the resolver
# short-circuited to loopback and the refusal came instantly (a node without a
# web server on :80 yet, e.g. the standalone svc-net-tor variant).
_REACHED_ON_CLOSE = ("closed connection", "RemoteDisconnected", "Connection refused")

# curl over the Tor SOCKS: rc 0 (response), 52 (empty reply) and 56 (reset)
# all require a completed rendezvous — the descriptor is published, which is
# what this gate waits for. rc 7 (SOCKS failure: no descriptor) and timeouts
# stay failures.
_CURL_REACHED_RCS = (0, 52, 56)


def check_internal(onion: str) -> str | None:
    try:
        urllib.request.urlopen(f"http://{onion}/", timeout=15)
    except urllib.error.HTTPError:
        return None
    except Exception as exc:  # any transport error means not ready yet
        detail = f"{type(exc).__name__}: {exc}"
        if any(token in detail for token in _REACHED_ON_CLOSE):
            return None
        return f"internal (loopback fast path): {detail}"
    return None


def check_external(onion: str, socks: str) -> str | None:
    result = subprocess.run(
        [
            "curl",
            "--silent",
            "--show-error",
            "--socks5-hostname",
            socks,
            "--max-time",
            "30",
            "--output",
            "/dev/null",
            f"http://{onion}/",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in _CURL_REACHED_RCS:
        return f"external (Tor SOCKS): curl rc={result.returncode} {result.stderr.strip()[:160]}"
    return None


def main(argv: list[str]) -> None:
    usage = "usage: onion_self_reach.py <internal|external|both> <node_onion> [socks_host:port]"
    if len(argv) < 3:
        sys.exit(usage)
    mode, onion = argv[1], argv[2]
    socks = argv[3] if len(argv) > 3 else None

    if mode in ("external", "both") and not socks:
        sys.exit(usage)

    error = None
    if mode in ("internal", "both"):
        error = check_internal(onion)
    if not error and mode in ("external", "both"):
        error = check_external(onion, socks)
    if mode not in ("internal", "external", "both"):
        sys.exit(usage)
    if error:
        sys.exit(error)


if __name__ == "__main__":
    main(sys.argv)
