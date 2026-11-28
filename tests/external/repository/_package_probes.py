"""Package index probes for the availability test.

Queries the official package index of each default distribution in
parallel instead of installing anything, so the whole registry is checked
in seconds rather than one container build per package.

A package that the index positively reports as absent fails the test. Only
the declared exemptions warn: a package from a third-party repository, and
a virtual name its index does not list. Any other probe that cannot reach
its index leaves availability unknown, which fails the test as well,
because a run that verified nothing must not report green. Ubuntu's index
is read from the first mirror of INFINITO_APT_UBUNTU_MIRRORS that serves
every pocket, in declared order.
"""

from __future__ import annotations

import http.client
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

from utils.env.parser import env_setting
from utils.packages.schema import (
    SOURCE_AUR,
    SOURCE_COPR,
    SOURCE_DOWNLOAD,
    SOURCE_FLATPAK,
)

from ._host_gate import host_gate

_TIMEOUT = 20
_MAX_WORKERS = 16
_USER_AGENT = "infinito-nexus package availability check"
_PER_HOST_REQUESTS = 2
_RETRY_ATTEMPTS = 4
_RETRY_BACKOFF = 1.0
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_DOWNLOAD_ABSENT = frozenset({403, 404})
"""Statuses that mean the vendor no longer serves the pinned artefact. The
CDN behind downloads.cursor.com answers 403, not 404, for an object that is
not there, so treating only 404 as absent would miss a rotated release."""

DEBIAN_SUITE = "stable"
UBUNTU_SUITE = "noble"
FEDORA_RELEASE = "f44"
CENTOS_STREAM = "10-stream"
EPEL_BRANCH = f"epel{CENTOS_STREAM.split('-', maxsplit=1)[0]}"
EPEL_BOOTSTRAP = "epel-release"

BOOTSTRAP_BASEURL: dict[str, str] = {
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
    url: str | None = None


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
    with host_gate(url, _PER_HOST_REQUESTS):
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


def _probe_flathub(name: str) -> tuple[bool | None, str]:
    status, _body = _get(f"https://flathub.org/api/v2/appstream/{name}")
    if status == 200:
        return True, "Flathub"
    if status == 404:
        return False, "Flathub"
    return None, f"Flathub returned HTTP {status}"


UBUNTU_MIRRORS_KEY = "INFINITO_APT_UBUNTU_MIRRORS"


class AptIndex(NamedTuple):
    mirrors: tuple[str, ...]
    suites: tuple[str, ...]
    components: tuple[str, ...]


APT_INDEX: dict[str, AptIndex] = {
    "debian": AptIndex(
        ("http://deb.debian.org/debian/",),
        (DEBIAN_SUITE, f"{DEBIAN_SUITE}-updates"),
        ("main", "contrib", "non-free", "non-free-firmware"),
    ),
    "ubuntu": AptIndex(
        tuple(env_setting(UBUNTU_MIRRORS_KEY).split()),
        (UBUNTU_SUITE, f"{UBUNTU_SUITE}-updates", f"{UBUNTU_SUITE}-security"),
        ("main", "universe", "restricted", "multiverse"),
    ),
}
"""The pockets a default install actually resolves against, and the mirrors
it reads them from in fallback order. Ubuntu ships packages such as 0ad only
in -updates, so probing the release pocket alone reports a declared package
as absent."""

_APT_INDEX_CACHE: dict[str, tuple[set[str] | None, str]] = {}
_APT_INDEX_LOCK = threading.Lock()


def _read_apt_mirror(mirror: str, index: AptIndex) -> tuple[set[str] | None, str]:
    """Read every pocket of one mirror, or none of them.

    Args:
        mirror: base URL of the archive, as the mirror list spells it.
        index: the suites and components to read.

    Returns:
        The binary and virtual package names across all pockets together
        with the mirror read, or None with the first pocket that failed.
    """
    host = urllib.parse.urlsplit(mirror).hostname
    names: set[str] = set()
    for suite in index.suites:
        for component in index.components:
            url = (
                f"{mirror.rstrip('/')}/dists/{suite}"
                f"/{component}/binary-amd64/Packages.xz"
            )
            try:
                status, body = _get(url)
            except (OSError, http.client.HTTPException) as exc:
                return None, f"{host}: {exc}"
            if status != 200:
                return None, f"{host} returned HTTP {status} for {url}"
            try:
                text = lzma.decompress(body).decode("utf-8", "replace")
            except lzma.LZMAError as exc:
                return None, f"{host}: {exc} for {url}"
            for line in text.splitlines():
                if line.startswith("Package: "):
                    names.add(line[len("Package: ") :].strip())
                elif line.startswith("Provides: "):
                    for entry in line[len("Provides: ") :].split(","):
                        names.add(entry.split("(")[0].strip())
    return names, f"{host}/{index.suites[0]}"


def _load_apt_index(index: AptIndex) -> tuple[set[str] | None, str]:
    """Read the index from the first mirror that serves every pocket.

    Args:
        index: the mirrors in fallback order, the suites and the components.

    Returns:
        The names and the mirror read, or None with every mirror's failure.
    """
    failures: list[str] = []
    for mirror in index.mirrors:
        names, detail = _read_apt_mirror(mirror, index)
        if names is not None:
            return names, detail
        failures.append(detail)
    return None, "; ".join(failures)


def _apt_index_names(distro: str) -> tuple[set[str] | None, str]:
    """Load a distribution's binary index once per run, answer from memory.

    Args:
        distro: key into APT_INDEX naming the mirrors, suites and components.

    Returns:
        The set of binary and virtual package names in the suite, or None
        together with each mirror's fetch error when no mirror could be read.
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


def _probe_mdapi(branch: str, name: str) -> tuple[bool | None, str]:
    """Ask Fedora's metadata API whether ``branch`` carries ``name``.

    Args:
        branch: an mdapi branch, such as ``f44`` or ``epel10``.
        name: the binary package name as the declaration spells it.

    Returns:
        Availability, or None with the reason the index stayed unknown.
    """
    status, _ = _get(
        f"https://mdapi.fedoraproject.org/{branch}/pkg/{urllib.parse.quote(name)}"
    )
    if status == 200:
        return True, f"mdapi {branch}"
    if status in (400, 404):
        return False, f"mdapi {branch}"
    return None, f"mdapi returned HTTP {status}"


def _probe_fedora(name: str) -> tuple[bool | None, str]:
    return _probe_mdapi(FEDORA_RELEASE, name)


def _copr_chroot(repo: dict, distro: str) -> str:
    """The chroot the install enables for a COPR declaration.

    Args:
        repo: the declaration's repository; an explicit ``chroot`` wins.
        distro: the probed distribution key; without an explicit chroot it
            selects the one ``community.general.copr`` falls back to.
    """
    if repo.get("chroot"):
        return str(repo["chroot"])
    if distro == "fedora":
        return f"fedora-{FEDORA_RELEASE.removeprefix('f')}-x86_64"
    return f"epel-{CENTOS_STREAM.split('-', maxsplit=1)[0]}-x86_64"


def _probe_copr(repo: dict, distro: str, name: str) -> tuple[bool | None, str]:
    """Ask the COPR API whether the project built ``name`` for the enabled chroot.

    Args:
        repo: the declaration's repository, ``copr`` being ``owner/project``.
        distro: the probed distribution key.
        name: the binary package name as the declaration spells it.

    Returns:
        Availability, or None with the reason the index stayed unknown.
    """
    owner, project = str(repo["copr"]).split("/", maxsplit=1)
    chroot = _copr_chroot(repo, distro)
    query = urllib.parse.urlencode(
        {
            "ownername": owner,
            "projectname": project,
            "packagename": name,
            "with_latest_succeeded_build": "True",
        }
    )
    status, body = _get(f"https://copr.fedorainfracloud.org/api_3/package/?{query}")
    if status == 404:
        return False, f"copr {repo['copr']} has no package {name}"
    if status != 200:
        return None, f"copr API returned HTTP {status}"
    build = json.loads(body)["builds"]["latest_succeeded"]
    built = sorted(build["chroots"]) if build else []
    if chroot in built:
        return True, f"copr {repo['copr']} {chroot}"
    return False, f"copr {repo['copr']} builds {name} for {built}, not {chroot}"


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
    if (
        isinstance(repo, dict)
        and not repo.get("baseurl")
        and repo.get("bootstrap_package") == EPEL_BOOTSTRAP
    ):
        return _probe_mdapi(EPEL_BRANCH, name)

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


def _probe_download(url: str) -> tuple[bool | None, str]:
    """Ask whether the vendor still serves the pinned artefact.

    Args:
        url: the https URL the declaration pins.

    Returns:
        Whether the artefact is served, and the host that answered.
    """
    request = urllib.request.Request(  # noqa: S310 - the schema admits https URLs only
        url, method="HEAD", headers={"User-Agent": _USER_AGENT}
    )
    host = urllib.parse.urlsplit(url).netloc
    with host_gate(url, _PER_HOST_REQUESTS):
        for attempt in range(_RETRY_ATTEMPTS):
            try:
                with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:  # noqa: S310 - the schema admits https URLs only
                    return response.getcode() == 200, host
            except urllib.error.HTTPError as exc:
                if exc.code in _RETRY_STATUS and attempt < _RETRY_ATTEMPTS - 1:
                    time.sleep(_RETRY_BACKOFF * 2**attempt)
                    continue
                absent = False if exc.code in _DOWNLOAD_ABSENT else None
                return absent, f"{host} (HTTP {exc.code})"
    raise AssertionError("unreachable")


def _probe(probe: Probe) -> Outcome:
    external = _externally_managed(probe.repo)
    if external:
        return Outcome(probe, None, f"third-party repository: {external}", True)
    try:
        if probe.source == SOURCE_DOWNLOAD:
            available, detail = _probe_download(probe.url)
        elif probe.source == SOURCE_AUR:
            available, detail = _probe_aur(probe.name)
        elif probe.source == SOURCE_FLATPAK:
            available, detail = _probe_flathub(probe.name)
        elif probe.source == SOURCE_COPR:
            available, detail = _probe_copr(probe.repo, probe.distro, probe.name)
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
