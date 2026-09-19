"""Every addon pinned to a release archive still resolves upstream.

An addon may carry ``config.archive``: the deploy fetches that archive and
unpacks it instead of letting the app store pick the newest release. The pin
exists because a store can advertise a release whose artifact was never
published, and a deploy has no way to fall back from that.

The pin is worth exactly as long as the artifact outlives it. When upstream
retires the release, every deploy of that role fails at install time with a 404
and nothing in the failure names the declaration as the cause. The same shape
already cost this repository a red CI job on two runs, in the opposite
direction: the store offered a version whose archive answered 404.

The declaration's shape is a repository fact and is asserted. Whether the
archive is still served is a network fact, so a timeout or a refused connection
is reported as unverified rather than failing, the way the sibling external
checks do: a firewalled runner must not turn a good pin red. An answer that
contradicts the pin is a defect in the repository and does fail.
"""

from __future__ import annotations

import concurrent.futures
import unittest
from pathlib import Path
from urllib.parse import urlsplit

import requests

from utils.annotations.message import warning
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

_ADDON_GLOB = "*/meta/addons/*.yml"
_USER_AGENT = "infinito-nexus-addon-pin-check"
_TIMEOUT_SECONDS = 20
_MAX_WORKERS = 4


def _pinned_archives() -> list[tuple[str, str, str]]:
    """Every ``(role, addon, archive)`` an addon pins, in path order."""
    found: list[tuple[str, str, str]] = []
    for addon_file in sorted((PROJECT_ROOT / "roles").glob(_ADDON_GLOB)):
        spec = load_yaml_any(str(addon_file), default_if_missing={}) or {}
        archive = (spec.get("config") or {}).get("archive")
        if not archive:
            continue
        role = addon_file.parent.parent.parent.name
        found.append((role, addon_file.stem, str(archive)))
    return found


def _relative(role: str, addon: str) -> str:
    return str(Path("roles") / role / "meta" / "addons" / f"{addon}.yml")


def _reachable(url: str) -> tuple[str, str]:
    """Return (kind, detail); a redirect to a release CDN counts as reachable."""
    try:
        response = requests.get(
            url,
            allow_redirects=True,
            headers={"User-Agent": _USER_AGENT, "Range": "bytes=0-0"},
            stream=True,
            timeout=_TIMEOUT_SECONDS,
        )
        try:
            status = response.status_code
        finally:
            response.close()
    except requests.Timeout as exc:
        return "unverified", f"Timeout: {exc}"
    except requests.RequestException as exc:
        return "unverified", f"{type(exc).__name__}: {exc}"

    if status < 400:
        return "ok", f"HTTP {status}"
    return "gone", f"HTTP {status}"


class TestPinnedAddonArchivesAvailable(unittest.TestCase):
    def test_every_pinned_archive_is_an_absolute_url(self) -> None:
        malformed = [
            f"{role}.{addon}: {archive!r} is not an absolute URL"
            for role, addon, archive in _pinned_archives()
            if not urlsplit(archive).scheme or not urlsplit(archive).netloc
        ]
        self.assertFalse(
            malformed,
            f"{len(malformed)} addon pin(s) cannot be fetched. 'config.archive' "
            "must be an absolute URL to a release artifact:\n"
            + "\n".join(f"  {line}" for line in malformed),
        )

    def test_every_pinned_archive_is_still_served(self) -> None:
        pins = _pinned_archives()
        if not pins:
            self.skipTest("no addon pins a release archive")

        with concurrent.futures.ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            answers = list(pool.map(_reachable, [archive for _, _, archive in pins]))

        retired = []
        for (role, addon, archive), (kind, detail) in zip(pins, answers, strict=True):
            if kind == "ok":
                continue
            if kind == "unverified":
                warning(
                    f"{role}.{addon}: {archive} was not checked ({detail})",
                    title="Addon pin unverified",
                    file=_relative(role, addon),
                )
                continue
            retired.append(f"{role}.{addon}: {archive} answered {detail}")

        self.assertFalse(
            retired,
            f"{len(retired)} pinned addon archive(s) are gone upstream. Every "
            "deploy of the role fails at install time until the pin moves to a "
            "release that is still published:\n"
            + "\n".join(f"  {line}" for line in retired),
        )
