"""One concurrency gate per host, shared by the probe suites in this package.

Both suites fan a thread pool out over many URLs at once, and one host has
been measured refusing connections under that load while answering each
request fine on its own: archlinux.org, under 22 parallel package probes.
The gate bounds how many requests may be in flight against one hostname
and leaves total parallelism alone.

That measurement is the only one. An earlier version of this file also
named huggingface.co, which was wrong: those requests never left the
runner, because `huggingface.co` is pinned in the test container's
`/etc/hosts` to the local package cache. Do not add a host here without a
reproduction that shows the host itself refusing.

The limit belongs to the caller, not to this module: a package index
tolerates less than a general web host, and the URL prober opens a fresh
connection per request where a browser would reuse a kept-alive one. Gates
are keyed by host *and* limit, so one suite's budget cannot silently
become another's.
"""

from __future__ import annotations

import threading
import urllib.parse

_gates: dict[tuple[str, int], threading.Semaphore] = {}


def host_gate(url: str, limit: int) -> threading.Semaphore:
    """Return the gate shared by every URL on *url*'s host.

    Args:
        url: absolute URL that is about to be requested.
        limit: how many requests this suite may hold in flight per host.

    Returns:
        A semaphore to hold for the duration of the request.
    """
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return _gates.setdefault((host, limit), threading.Semaphore(limit))
