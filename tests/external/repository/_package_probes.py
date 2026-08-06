"""Package index probes for the availability test.

Queries the official package index of each default distribution in
parallel instead of installing anything, so the whole registry is checked
in seconds rather than one container build per package.

A package that the index positively reports as absent fails the test. A
network or index error is reported as a warning, because an unreachable
mirror says nothing about the declaration.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import NamedTuple

from utils.packages.schema import SOURCE_AUR

_TIMEOUT = 20
_MAX_WORKERS = 16
_USER_AGENT = "infinito-nexus package availability check"

DEBIAN_SUITE = "stable"
UBUNTU_SUITE = "noble"
FEDORA_RELEASE = "f44"
CENTOS_STREAM = "10-stream"

BOOTSTRAP_BASEURL: dict[str, str] = {
    "epel-release": (
        "https://dl.fedoraproject.org/pub/epel/$releasever/Everything/$basearch/"
    ),
    "centos-release-nfs-ganesha11": (
        "https://mirror.stream.centos.org/SIGs/$releasever-stream"
        "/storage/$basearch/nfsganesha-11/"
    ),
}
"""Where a repository shipped as a package publishes its packages. A
declaration names the bootstrap package because that is what the install
needs; only this probe needs the URL behind it."""

_DEBIAN_MISSING_RE = re.compile(r"no such package", re.IGNORECASE)


class PackageAvailabilityWarning(UserWarning):
    """An index could not be consulted, so availability stays unknown."""


class Probe(NamedTuple):
    package_id: str
    distro: str
    name: str
    repo: dict | None
    source: str
    virtual: bool = False


class Outcome(NamedTuple):
    probe: Probe
    available: bool | None
    detail: str


def _get(url: str) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})  # noqa: S310 - literal https package index URLs only
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:  # noqa: S310 - literal https package index URLs only
            return response.getcode(), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""


def _probe_arch(name: str) -> tuple[bool | None, str]:
    query = urllib.parse.urlencode({"name": name})
    status, body = _get(f"https://archlinux.org/packages/search/json/?{query}")
    if status != 200:
        return None, f"archlinux.org returned HTTP {status}"
    payload = json.loads(body or b"{}")
    return bool(payload.get("results")), "official repositories"


def _probe_aur(name: str) -> tuple[bool | None, str]:
    query = urllib.parse.urlencode({"arg[]": name})
    status, body = _get(f"https://aur.archlinux.org/rpc/v5/info?{query}")
    if status != 200:
        return None, f"AUR RPC returned HTTP {status}"
    payload = json.loads(body or b"{}")
    return bool(payload.get("results")), "AUR"


def _probe_debian_like(host: str, suite: str, name: str) -> tuple[bool | None, str]:
    status, body = _get(f"https://{host}/{suite}/{urllib.parse.quote(name)}")
    if status == 404:
        return False, f"{host}/{suite}"
    if status != 200:
        return None, f"{host} returned HTTP {status}"
    if _DEBIAN_MISSING_RE.search(body.decode("utf-8", "replace")):
        return False, f"{host}/{suite}"
    return True, f"{host}/{suite}"


def _probe_fedora(name: str) -> tuple[bool | None, str]:
    status, _ = _get(
        f"https://mdapi.fedoraproject.org/{FEDORA_RELEASE}/pkg/"
        f"{urllib.parse.quote(name)}"
    )
    if status == 200:
        return True, f"mdapi {FEDORA_RELEASE}"
    if status in (400, 404):
        return False, f"mdapi {FEDORA_RELEASE}"
    return None, f"mdapi returned HTTP {status}"


def _centos_repo_baseurl(repo: dict | None) -> str | None:
    if not isinstance(repo, dict):
        return None
    baseurl = repo.get("baseurl") or BOOTSTRAP_BASEURL.get(
        str(repo.get("bootstrap_package"))
    )
    if not baseurl:
        return None
    return (
        str(baseurl)
        .replace("$releasever", CENTOS_STREAM.split("-", maxsplit=1)[0])
        .replace("$basearch", "x86_64")
    )


def _centos_listings(name: str, repo: dict | None) -> list[str] | None:
    if repo:
        baseurl = _centos_repo_baseurl(repo)
        if baseurl is None:
            return None
        return [f"{baseurl.rstrip('/')}/Packages/{name[0].lower()}/"]
    stream = f"https://mirror.stream.centos.org/{CENTOS_STREAM}"
    return [
        f"{stream}/BaseOS/x86_64/os/Packages/",
        f"{stream}/AppStream/x86_64/os/Packages/",
    ]


def _probe_centos(name: str, repo: dict | None) -> tuple[bool | None, str]:
    listings = _centos_listings(name, repo)
    if listings is None:
        return None, "the inline repository definition declares no baseurl"

    pattern = re.compile(rf'href="{re.escape(name)}-[0-9][^"]*\.rpm"')
    unreachable: list[str] = []
    for base in listings:
        status, body = _get(base)
        if status != 200:
            unreachable.append(f"HTTP {status} for {base}")
            continue
        if pattern.search(body.decode("utf-8", "replace")):
            return True, base
    if unreachable:
        return None, "; ".join(unreachable)
    return False, " and ".join(listings)


def _externally_managed(repo: dict | None) -> str | None:
    if isinstance(repo, dict) and repo.get("managed_externally"):
        return str(repo["managed_externally"])
    return None


def _probe(probe: Probe) -> Outcome:
    external = _externally_managed(probe.repo)
    if external:
        return Outcome(probe, None, f"third-party repository: {external}")
    try:
        if probe.source == SOURCE_AUR:
            available, detail = _probe_aur(probe.name)
        elif probe.distro == "arch":
            available, detail = _probe_arch(probe.name)
        elif probe.distro == "debian":
            available, detail = _probe_debian_like(
                "packages.debian.org", DEBIAN_SUITE, probe.name
            )
        elif probe.distro == "ubuntu":
            available, detail = _probe_debian_like(
                "packages.ubuntu.com", UBUNTU_SUITE, probe.name
            )
        elif probe.distro == "fedora":
            available, detail = _probe_fedora(probe.name)
        else:
            available, detail = _probe_centos(probe.name, probe.repo)
    except Exception as exc:
        return Outcome(probe, None, f"{type(exc).__name__}: {exc}")
    if available is False and probe.virtual:
        return Outcome(probe, None, f"{detail} lists no such name; declared virtual")
    return Outcome(probe, available, detail)
