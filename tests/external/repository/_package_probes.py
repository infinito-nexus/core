"""Package index probes for the availability test.

Queries the official package index of each default distribution in
parallel instead of installing anything, so the whole registry is checked
in seconds rather than one container build per package.

A package that the index positively reports as absent fails the test. A
network or index error is reported as a warning, because an unreachable
mirror says nothing about the declaration.
"""

from __future__ import annotations

import io
import json
import lzma
import re
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import NamedTuple

from utils.packages.schema import SOURCE_AUR

_TIMEOUT = 20
_MAX_WORKERS = 16
_USER_AGENT = "infinito-nexus package availability check"
_PER_HOST_REQUESTS = 2
_RETRY_ATTEMPTS = 4
_RETRY_BACKOFF = 1.0
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_HOST_LOCKS: dict[str, threading.Semaphore] = {}

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
    declared: bool = False


def _get(url: str) -> tuple[int, bytes]:
    """Fetch one index URL, serialising and retrying per host.

    Args:
        url: absolute http(s) URL of a package index.

    Returns:
        The HTTP status and body; the body is empty for an error status.
    """
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})  # noqa: S310 - literal http(s) package index URLs only
    host = urllib.parse.urlsplit(url).hostname or ""
    with _HOST_LOCKS.setdefault(host, threading.Semaphore(_PER_HOST_REQUESTS)):
        for attempt in range(_RETRY_ATTEMPTS):
            try:
                with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:  # noqa: S310 - literal http(s) package index URLs only
                    return response.getcode(), response.read()
            except urllib.error.HTTPError as exc:
                if exc.code not in _RETRY_STATUS or attempt == _RETRY_ATTEMPTS - 1:
                    return exc.code, b""
            except OSError:
                if attempt == _RETRY_ATTEMPTS - 1:
                    raise
            time.sleep(_RETRY_BACKOFF * 2**attempt)
    raise AssertionError("unreachable")


ARCH_MIRROR = "geo.mirror.pkgbuild.com"
_ARCH_REPOS = ("core", "extra", "multilib")
_ARCH_INDEX_CACHE: dict[str, set[str] | str] = {}
_ARCH_INDEX_LOCK = threading.Lock()


def _desc_names(desc: str) -> set[str]:
    names: set[str] = set()
    section = ""
    for line in desc.splitlines():
        if line.startswith("%") and line.endswith("%"):
            section = line
        elif line and section in ("%NAME%", "%PROVIDES%"):
            names.add(line.split("=")[0].split("<")[0].strip())
    return names


def _load_arch_index() -> None:
    names: set[str] = set()
    for repo in _ARCH_REPOS:
        url = f"https://{ARCH_MIRROR}/{repo}/os/x86_64/{repo}.db"
        try:
            status, body = _get(url)
        except OSError as exc:
            _ARCH_INDEX_CACHE["error"] = f"{ARCH_MIRROR}: {exc}"
            return
        if status != 200:
            _ARCH_INDEX_CACHE["error"] = f"{ARCH_MIRROR} returned HTTP {status}"
            return
        with tarfile.open(fileobj=io.BytesIO(body), mode="r:*") as archive:
            for member in archive:
                if not member.name.endswith("/desc"):
                    continue
                handle = archive.extractfile(member)
                if handle is None:
                    continue
                names |= _desc_names(handle.read().decode("utf-8", "replace"))
    _ARCH_INDEX_CACHE["names"] = names


def _arch_index_names() -> tuple[set[str] | None, str]:
    """Load the Arch repo databases once per run and answer from memory.

    Returns:
        The set of package and provided names in core, extra and multilib,
        or None together with the fetch error when a database could not be
        read.
    """
    with _ARCH_INDEX_LOCK:
        if not _ARCH_INDEX_CACHE:
            _load_arch_index()
        error = _ARCH_INDEX_CACHE.get("error")
        if error is not None:
            return None, str(error)
        names = _ARCH_INDEX_CACHE["names"]
        assert isinstance(names, set)
        return names, f"{ARCH_MIRROR} core+extra+multilib"


def _probe_arch(name: str) -> tuple[bool | None, str]:
    names, detail = _arch_index_names()
    if names is None:
        return None, detail
    return name in names, detail


def _probe_aur(name: str) -> tuple[bool | None, str]:
    query = urllib.parse.urlencode({"arg[]": name})
    status, body = _get(f"https://aur.archlinux.org/rpc/v5/info?{query}")
    if status != 200:
        return None, f"AUR RPC returned HTTP {status}"
    payload = json.loads(body or b"{}")
    return bool(payload.get("results")), "AUR"


DEBIAN_MIRROR = "deb.debian.org"
UBUNTU_MIRROR = "archive.ubuntu.com"


class AptIndex(NamedTuple):
    mirror: str
    path: str
    suites: tuple[str, ...]
    components: tuple[str, ...]


APT_INDEX: dict[str, AptIndex] = {
    "debian": AptIndex(
        DEBIAN_MIRROR,
        "debian",
        (DEBIAN_SUITE, f"{DEBIAN_SUITE}-updates"),
        ("main", "contrib", "non-free", "non-free-firmware"),
    ),
    "ubuntu": AptIndex(
        UBUNTU_MIRROR,
        "ubuntu",
        (UBUNTU_SUITE, f"{UBUNTU_SUITE}-updates", f"{UBUNTU_SUITE}-security"),
        ("main", "universe", "restricted", "multiverse"),
    ),
}
"""The pockets a default install actually resolves against. Ubuntu ships
packages such as 0ad only in -updates, so probing the release pocket alone
reports a declared package as absent."""

_APT_INDEX_CACHE: dict[str, tuple[set[str] | None, str]] = {}
_APT_INDEX_LOCK = threading.Lock()


def _load_apt_index(index: AptIndex) -> tuple[set[str] | None, str]:
    names: set[str] = set()
    for suite in index.suites:
        for component in index.components:
            url = (
                f"http://{index.mirror}/{index.path}/dists/{suite}"
                f"/{component}/binary-amd64/Packages.xz"
            )
            try:
                status, body = _get(url)
            except OSError as exc:
                return None, f"{index.mirror}: {exc}"
            if status != 200:
                return None, f"{index.mirror} returned HTTP {status} for {url}"
            for line in lzma.decompress(body).decode("utf-8", "replace").splitlines():
                if line.startswith("Package: "):
                    names.add(line[len("Package: ") :].strip())
                elif line.startswith("Provides: "):
                    for entry in line[len("Provides: ") :].split(","):
                        names.add(entry.split("(")[0].strip())
    return names, f"{index.mirror}/{index.suites[0]}"


def _apt_index_names(distro: str) -> tuple[set[str] | None, str]:
    """Load a distribution's binary index once per run, answer from memory.

    Args:
        distro: key into APT_INDEX naming the mirror, suite and components.

    Returns:
        The set of binary and virtual package names in the suite, or None
        together with the fetch error when the mirror could not be read.
    """
    with _APT_INDEX_LOCK:
        if distro not in _APT_INDEX_CACHE:
            _APT_INDEX_CACHE[distro] = _load_apt_index(APT_INDEX[distro])
        return _APT_INDEX_CACHE[distro]


def _probe_apt(distro: str, name: str) -> tuple[bool | None, str]:
    names, detail = _apt_index_names(distro)
    if names is None:
        return None, detail
    return name in names, detail


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
        return Outcome(probe, None, f"third-party repository: {external}", True)
    try:
        if probe.source == SOURCE_AUR:
            available, detail = _probe_aur(probe.name)
        elif probe.distro == "arch":
            available, detail = _probe_arch(probe.name)
        elif probe.distro in APT_INDEX:
            available, detail = _probe_apt(probe.distro, probe.name)
        elif probe.distro == "fedora":
            available, detail = _probe_fedora(probe.name)
        else:
            available, detail = _probe_centos(probe.name, probe.repo)
    except Exception as exc:
        return Outcome(probe, None, f"{type(exc).__name__}: {exc}")
    if available is False and probe.virtual:
        return Outcome(
            probe, None, f"{detail} lists no such name; declared virtual", True
        )
    return Outcome(probe, available, detail)
