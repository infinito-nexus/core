from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import SplitResult, urlsplit

from utils.cache.artefact_urls import (
    ARGOS_NET,
    GITHUB,
    GITHUB_RAW,
    HUB,
    REF_OF,
    REVISION_OF,
    SCHEME,
    SLASH,
    TREE,
    UNPACKED,
    checked_base,
    path_segments,
    tree_path,
    tree_root,
    unpack_path,
    url_for,
)
from utils.cache.hosts import (
    HTTPS_PORT,
    claim,
    declarations,
    raw_section,
    role_dirs,
    section,
)
from utils.digests import COMMIT, SHA256

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from utils.cache.hosts import CachedHost, CachedRepo, Declarations

__all__ = [
    "ARGOS_NET",
    "GITHUB",
    "GITHUB_RAW",
    "HUB",
    "TREE",
    "UNPACKED",
    "Artefact",
    "artefacts",
    "breaches",
    "checked",
    "pin_problems",
    "problems",
    "records",
    "shape_breaches",
    "store_bytes",
    "tree_path",
    "tree_root",
    "unpack_path",
    "unpacked_bytes",
    "url_for",
]

SECTION = "artefacts"
KEYS = ("url", "revision", "sha256", "bytes")
UNPACKED_KEY = "unpacked_bytes"
NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")
SIZE = re.compile(r"[1-9][0-9]*")
PATH = re.compile(r"[A-Za-z0-9._~/-]+")
PATH_CHARSET = "A-Z a-z 0-9 . _ ~ / -"
DOT = "."
COMMIT_RULE = (COMMIT, "a 40-digit lowercase hex commit; branches and tags move")


@dataclass(frozen=True)
class Artefact:
    """
    Args:
        name: the key it is declared under, unique across every role.
        url: the upstream URL at the pinned revision.
        revision: the immutable revision, the ref segment of ``url``.
        sha256: the lowercase hex digest of the file.
        size: its size in bytes as declared, the ``bytes`` key.
        role: the role that declared it.
        unpacked: the sum of the file sizes its archive lists, the
            ``unpacked_bytes`` key an Argos package carries; empty otherwise.
    """

    name: str
    url: str
    revision: str
    sha256: str
    size: str
    role: str = ""
    unpacked: str = ""


def _declared(role_dir: Path) -> Iterator[Artefact]:
    for name, entry in section(role_dir, SECTION):
        yield Artefact(
            name=name,
            url=str(entry.get("url", "")),
            revision=str(entry.get("revision", "")),
            sha256=str(entry.get("sha256", "")),
            size=str(entry.get("bytes", "")),
            role=role_dir.name,
            unpacked=str(entry.get(UNPACKED_KEY, "")),
        )


def artefacts() -> list[Artefact]:
    """
    Returns:
        Every declared artefact, sorted by name.

    Raises:
        ValueError: a second role declares a name, even identically.
    """
    seen: dict[str, Artefact] = {}
    for role_dir in role_dirs():
        for artefact in _declared(role_dir):
            claim(seen, artefact.name, artefact, "artefact")
    return [seen[name] for name in sorted(seen)]


def _slashed(url: str) -> str:
    return url.rstrip(SLASH) + SLASH


def _holders(url: str, cache: Declarations) -> list[CachedRepo]:
    under = [
        repo
        for repo in cache.repos
        if repo.upstream and url.startswith(_slashed(repo.upstream))
    ]
    longest = max((len(_slashed(repo.upstream)) for repo in under), default=0)
    return [repo for repo in under if len(_slashed(repo.upstream)) == longest]


def _served(cache: Declarations, host: str) -> CachedHost | None:
    return next((entry for entry in cache.hosts if entry.host == host), None)


def _repository_problem(url: str, parts: SplitResult, cache: Declarations) -> str:
    holders = _holders(url, cache)
    if not holders:
        return (
            "url is under no cache: repository upstream, so no prefetch through "
            "Nexus reaches it"
        )
    if len(holders) > 1:
        names = ", ".join(repo.name for repo in holders)
        return (
            f"url lies under the upstream of {names} alike, so no one repository "
            "holds it"
        )
    holder, host = holders[0], parts.hostname or ""
    entry = _served(cache, host)
    if entry is not None and not entry.at_base():
        return (
            f"cache: hosts: {host} lists no {HTTPS_PORT} under ports and is not "
            f'declared hijack: "false", so no route answers the {SCHEME} url'
        )
    path, repo = entry.tls_route() if entry is not None else ("", "")
    if repo != holder.name:
        return (
            f"no cache: hosts: route of {host} serves {holder.name} on its TLS "
            f"listener, so <base>/{host}/<path> misses it"
        )
    if _slashed(f"{SCHEME}://{host}{path}") != _slashed(holder.upstream):
        return (
            f"the {host} route {path} serves {holder.name}, whose upstream is not "
            f"{SCHEME}://{host}{path}, so <base>/{host}/<path> fetches another file"
        )
    return ""


def _revision_problem(revision: str, host: str, segments: list[str]) -> str:
    pattern, shape = REVISION_OF.get(host, COMMIT_RULE)
    if not pattern.fullmatch(revision):
        return f"revision {revision!r} is not {shape}"
    ref_of = REF_OF.get(host)
    if ref_of is None:
        return (
            f"host {host or '<none>'} has no known ref layout, so the revision "
            "cannot be bound to the url"
        )
    ref = ref_of(segments)
    if not ref:
        return f"url path does not follow the {host} file layout"
    if ref != revision:
        return f"revision {revision!r} is not the ref segment {ref!r} of the url"
    return ""


def _split(url: str) -> SplitResult | None:
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    return parts if parts.scheme == SCHEME and parts.hostname else None


def _url_problems(url: str, parts: SplitResult) -> list[str]:
    found: list[str] = []
    if not (url.isascii() and url.isprintable()) or " " in url:
        found.append("url carries whitespace, a control or a non-ASCII character")
    if "@" in parts.netloc:
        found.append("url carries userinfo")
    if ":" in parts.netloc:
        found.append("url carries an explicit port")
    if "%" in url:
        found.append("url carries a percent escape")
    if "?" in url:
        found.append("url carries a query")
    if "#" in url:
        found.append("url carries a fragment")
    if not PATH.fullmatch(parts.path):
        found.append(f"url path carries a character outside {PATH_CHARSET}")
    if any(not s.strip(DOT) for s in path_segments(parts.path)):
        found.append("url path has an empty or all-dot segment")
    return found


def pin_problems(url: str, revision: str, sha256: str, size: str) -> list[str]:
    """
    Args:
        url: the upstream URL at the pinned revision.
        revision: the immutable revision, the ref segment of ``url``.
        sha256: the lowercase hex digest of the file.
        size: its size in bytes as declared.

    Returns:
        Every way the four pins break the manifest contract; empty when none.
    """
    parts = _split(url)
    if parts is None:
        found = [f"url {url!r} is not an absolute {SCHEME} URL"]
        host, segments = "", []
    else:
        found = _url_problems(url, parts)
        host, segments = parts.hostname or "", path_segments(parts.path)
    found.append(_revision_problem(revision, host, segments))
    if not SHA256.fullmatch(sha256):
        found.append("sha256 is not 64 lowercase hex digits")
    if not SIZE.fullmatch(size):
        found.append(f"bytes {size!r} is not a positive decimal integer")
    return [problem for problem in found if problem]


def problems(artefact: Artefact, cache: Declarations) -> list[str]:
    """
    Args:
        artefact: the declaration to check.
        cache: the repositories and hosts, as `declarations` returns them.

    Returns:
        Every way *artefact* breaks the manifest contract; empty when none.
    """
    found = pin_problems(
        artefact.url, artefact.revision, artefact.sha256, artefact.size
    )
    parts = _split(artefact.url)
    if parts is not None:
        found.append(_repository_problem(artefact.url, parts, cache))
    if not NAME.fullmatch(artefact.name):
        found.append(f"name {artefact.name!r} does not match {NAME.pattern}")
    found.append(_unpacked_problem(artefact))
    return [problem for problem in found if problem]


def _unpacked_problem(artefact: Artefact) -> str:
    if not unpack_path(artefact.url, artefact.sha256):
        return (
            f"{UNPACKED_KEY} is declared, but only an Argos package is unpacked"
            if artefact.unpacked
            else ""
        )
    if not SIZE.fullmatch(artefact.unpacked):
        return (
            f"{UNPACKED_KEY} {artefact.unpacked!r} is not a positive decimal "
            "integer; an Argos package declares what its archive lists"
        )
    return ""


def _entry_problems(role: str, name: str, entry: object) -> list[str]:
    if not isinstance(entry, dict):
        return [f"{role}/{name}: the entry is a {type(entry).__name__}, not a mapping"]
    allowed = (*KEYS, UNPACKED_KEY)
    return [
        f"{role}/{name}: key {key!r} is not one of {', '.join(allowed)}"
        for key in sorted(set(entry) - set(allowed))
    ]


def _shape_problems(role_dir: Path) -> list[str]:
    entries = raw_section(role_dir, SECTION)
    if entries is None:
        return []
    if not isinstance(entries, dict):
        kind = type(entries).__name__
        return [f"{role_dir.name}: cache: {SECTION}: is a {kind}, not a mapping"]
    return [
        line
        for name, entry in entries.items()
        for line in _entry_problems(role_dir.name, str(name), entry)
    ]


def _digest_conflicts(declared: list[Artefact]) -> list[str]:
    sizes: dict[str, dict[str, str]] = {}
    for item in declared:
        sizes.setdefault(item.sha256, {})[f"{item.role}/{item.name}"] = (
            f"{item.size} unpacked {item.unpacked}" if item.unpacked else item.size
        )
    return [
        f"sha256 {digest} is declared with different sizes: "
        + ", ".join(f"{who} {size}" for who, size in sorted(by.items()))
        for digest, by in sorted(sizes.items())
        if len(set(by.values())) > 1
    ]


def shape_breaches() -> list[str]:
    """
    Returns:
        Every role's ``artefacts:`` section or entry that is not a mapping, and
        every entry key beyond the four and ``unpacked_bytes``, one line each:
        ``<role>: <problem>``
        or ``<role>/<name>: <problem>``.
    """
    return [line for role_dir in role_dirs() for line in _shape_problems(role_dir)]


def breaches(declared: list[Artefact]) -> list[str]:
    """
    Args:
        declared: the artefacts, as `artefacts` returns them.

    Returns:
        Every contract breach of *declared*, one line each:
        ``<role>/<name>: <problem>``, or one line per digest declared with two
        sizes.
    """
    cache = declarations()
    found = [
        f"{item.role}/{item.name}: {problem}"
        for item in declared
        for problem in problems(item, cache)
    ]
    found.extend(_digest_conflicts(declared))
    return found


def checked() -> list[Artefact]:
    """
    Returns:
        Every declared artefact, sorted by name.

    Raises:
        ValueError: a declaration has the wrong shape or an artefact breaks the
            contract; every breach is named.
    """
    declared = artefacts()
    broken = [*shape_breaches(), *breaches(declared)]
    if broken:
        raise ValueError(
            "artefacts breaking the manifest contract: " + "; ".join(broken)
        )
    return declared


def store_bytes(declared: list[Artefact]) -> int:
    """
    Args:
        declared: the artefacts the store holds, as `checked` returns them.

    Returns:
        The bytes the content-addressed store needs, each digest once.

    Raises:
        ValueError: one digest is declared with two different sizes.
    """
    conflicts = _digest_conflicts(declared)
    if conflicts:
        raise ValueError("; ".join(conflicts))
    return sum({item.sha256: int(item.size) for item in declared}.values())


def unpacked_bytes(declared: list[Artefact]) -> int:
    """
    Args:
        declared: the artefacts the store holds, as `checked` returns them.

    Returns:
        The bytes the unpacked copies need on top of `store_bytes`, each
        digest once.
    """
    return sum(
        {
            item.sha256: int(item.unpacked)
            for item in declared
            if unpack_path(item.url, item.sha256)
        }.values()
    )


def records(base: str) -> dict[str, dict]:
    """
    Args:
        base: the artefact base each ``url`` is rewritten under; empty keeps
            the upstream, which stays in ``upstream`` either way.

    Returns:
        Every artefact as a template-ready record, keyed by name.

    Raises:
        ValueError: *base* is malformed, as `url_for` refuses it, or an
            artefact breaks the contract.
    """
    checked_base(base)
    return {
        item.name: {
            "name": item.name,
            "upstream": item.url,
            "url": url_for(item.url, base),
            "tree": tree_path(item.url),
            "root": tree_root(item.url),
            "unpack": unpack_path(item.url, item.sha256),
            "unpacked_bytes": int(item.unpacked or 0),
            "revision": item.revision,
            "sha256": item.sha256,
            "bytes": int(item.size),
            "role": item.role,
        }
        for item in checked()
    }
