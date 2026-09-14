"""External: the Ubuntu mirror list stays fast, fresh and official.

``INFINITO_APT_UBUNTU_MIRRORS`` orders the mirrors Ubuntu images fall back
through and the package cache proxies. The order is kept by hand; this test
says when it has to change:

* the first mirror answers ``InRelease`` within ``FIRST_MIRROR_MAX_SECONDS``
  (median of ``PROBES``), or the test names a later mirror that does;
* no mirror's ``-updates`` pocket lags the freshest one in the list by more
  than ``STALE_AFTER``;
* every mirror is the primary archive, a Canonical country alias, or an
  enabled official mirror in Launchpad's registry.

A mirror this host pins in /etc/hosts goes through the local package cache
and is not measured. An unreachable mirror or registry is a warning; the test
fails outright only when no mirror answers at all.
"""

from __future__ import annotations

import concurrent.futures
import email.utils
import json
import statistics
import time
import unittest
import urllib.parse
import urllib.request
import warnings
from datetime import timedelta
from typing import NamedTuple

from utils.cache.files import read_text
from utils.env.parser import env_setting

from ._package_probes import UBUNTU_SUITE

MIRRORS_KEY = "INFINITO_APT_UBUNTU_MIRRORS"
FIRST_MIRROR_MAX_SECONDS = 5.0
PROBES = 3
STALE_AFTER = timedelta(hours=24)
TIMEOUT_SECONDS = 20
PRIMARY_ARCHIVE = "archive.ubuntu.com"
REGISTRY = "https://api.launchpad.net/devel/ubuntu/archive_mirrors?ws.size=75"
USER_AGENT = "infinito-nexus mirror check"


class MirrorCheckWarning(UserWarning):
    """A mirror or the mirror registry could not be consulted."""


class Measurement(NamedTuple):
    mirror: str
    seconds: float | None
    released: float | None
    detail: str


def _host(url: str) -> str:
    return urllib.parse.urlsplit(url).hostname or ""


def _pinned_hosts() -> set[str]:
    names: set[str] = set()
    for line in read_text("/etc/hosts").splitlines():
        names.update(line.split("#", 1)[0].split()[1:])
    return names


def _get(url: str) -> tuple[float, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310 - literal http(s) mirror and registry URLs only
    start = time.monotonic()
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 - literal http(s) mirror and registry URLs only
        return time.monotonic() - start, response.read()


def _released(body: bytes) -> float | None:
    for line in body.decode("utf-8", "replace").splitlines():
        if line.startswith("Date: "):
            return email.utils.parsedate_to_datetime(line[6:].strip()).timestamp()
    return None


def _measure(mirror: str) -> Measurement:
    url = f"{mirror.rstrip('/')}/dists/{UBUNTU_SUITE}-updates/InRelease"
    timings: list[float] = []
    released = None
    try:
        for _ in range(PROBES):
            seconds, body = _get(url)
            timings.append(seconds)
            released = released or _released(body)
    except OSError as exc:
        return Measurement(mirror, None, released, f"{type(exc).__name__}: {exc}")
    return Measurement(mirror, statistics.median(timings), released, url)


def _official_hosts() -> set[str] | None:
    hosts: set[str] = set()
    url: str | None = REGISTRY
    try:
        while url:
            page = json.loads(_get(url)[1])
            for entry in page.get("entries", []):
                if entry.get("enabled") and entry.get("status") == "Official":
                    hosts.update(
                        _host(entry[key])
                        for key in ("http_base_url", "https_base_url")
                        if entry.get(key)
                    )
            url = page.get("next_collection_link")
    except (OSError, ValueError) as exc:
        warnings.warn(
            f"Launchpad mirror registry unreadable, officiality unverified: {exc}",
            MirrorCheckWarning,
            stacklevel=1,
        )
        return None
    return hosts


def _order_problems(first: Measurement, answered: list[Measurement]) -> list[str]:
    if first.seconds is not None and first.seconds <= FIRST_MIRROR_MAX_SECONDS:
        return []
    faster = [
        m
        for m in answered
        if m.mirror != first.mirror and m.seconds <= FIRST_MIRROR_MAX_SECONDS
    ]
    took = "no answer" if first.seconds is None else f"{first.seconds:.1f} s"
    if not faster:
        warnings.warn(
            f"{first.mirror}: {took}, and no later mirror answers within "
            f"{FIRST_MIRROR_MAX_SECONDS:.0f} s either",
            MirrorCheckWarning,
            stacklevel=1,
        )
        return []
    best = min(faster, key=lambda m: m.seconds)
    return [
        (
            f"{first.mirror} is first but took {took} (limit "
            f"{FIRST_MIRROR_MAX_SECONDS:.0f} s); move it behind {best.mirror} "
            f"({best.seconds:.1f} s)"
        )
    ]


def _freshness_problems(answered: list[Measurement]) -> list[str]:
    dated = [m for m in answered if m.released is not None]
    if not dated:
        return []
    newest = max(m.released for m in dated)
    return [
        f"{m.mirror}: {UBUNTU_SUITE}-updates is "
        f"{(newest - m.released) / 3600:.0f} h behind the freshest mirror in the list"
        for m in dated
        if newest - m.released > STALE_AFTER.total_seconds()
    ]


def _registry_problems(mirrors: list[str]) -> list[str]:
    official = _official_hosts()
    if official is None:
        return []
    return [
        f"{mirror}: not the primary archive, a Canonical country alias, or an "
        "enabled official mirror in Launchpad's registry"
        for mirror in mirrors
        if not (
            _host(mirror) == PRIMARY_ARCHIVE
            or _host(mirror).endswith(f".{PRIMARY_ARCHIVE}")
            or _host(mirror) in official
        )
    ]


class TestAptUbuntuMirrors(unittest.TestCase):
    def test_mirror_list_is_fast_fresh_and_official(self) -> None:
        mirrors = env_setting(MIRRORS_KEY).split()
        self.assertGreaterEqual(
            len(mirrors), 2, f"{MIRRORS_KEY} needs a primary and a fallback mirror"
        )
        pinned = _pinned_hosts()
        measurable = [m for m in mirrors if _host(m) not in pinned]
        for mirror in sorted(set(mirrors) - set(measurable)):
            warnings.warn(
                f"{mirror}: pinned in /etc/hosts, so it answers through the local "
                "package cache here and is not measured",
                MirrorCheckWarning,
                stacklevel=1,
            )

        with concurrent.futures.ThreadPoolExecutor(max(len(measurable), 1)) as pool:
            results = list(pool.map(_measure, measurable))
        answered = [m for m in results if m.seconds is not None]
        for missing in (m for m in results if m.seconds is None):
            warnings.warn(
                f"{missing.mirror}: {missing.detail}", MirrorCheckWarning, stacklevel=1
            )
        if measurable and not answered:
            self.fail(
                "No Ubuntu mirror answered, so nothing was verified:\n"
                + "\n".join(f"  {m.mirror}: {m.detail}" for m in results)
            )

        problems: list[str] = []
        if mirrors[0] in measurable:
            first = next(m for m in results if m.mirror == mirrors[0])
            problems.extend(_order_problems(first, answered))
        problems.extend(_freshness_problems(answered))
        problems.extend(_registry_problems(mirrors))
        if problems:
            self.fail(
                f"{MIRRORS_KEY} needs an edit:\n"
                + "\n".join(f"  - {problem}" for problem in problems)
            )


if __name__ == "__main__":
    unittest.main()
