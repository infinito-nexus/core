from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import SplitResult, urlsplit

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
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from utils.cache.hosts import CachedHost, CachedRepo, Declarations

SECTION = "artefacts"
KEYS = ("url", "revision", "sha256", "bytes")
SCHEME = "https"
BASE_SCHEMES = frozenset({"http", SCHEME})
SHELL_DEFAULT_BASE = f"{SCHEME}:/"
NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")
SIZE = re.compile(r"[1-9][0-9]*")
PATH = re.compile(r"[A-Za-z0-9._~/-]+")
PATH_CHARSET = "A-Z a-z 0-9 . _ ~ / -"
DOT = "."
SLASH = "/"
HUB = "huggingface.co"
HUB_KINDS = frozenset({"datasets", "spaces"})
HUB_RESOLVE = "resolve"
GITHUB_RAW = "raw.githubusercontent.com"


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
    """

    name: str
    url: str
    revision: str
    sha256: str
    size: str
    role: str = ""


def _declared(role_dir: Path) -> Iterator[Artefact]:
    for name, entry in section(role_dir, SECTION):
        yield Artefact(
            name=name,
            url=str(entry.get("url", "")),
            revision=str(entry.get("revision", "")),
            sha256=str(entry.get("sha256", "")),
            size=str(entry.get("bytes", "")),
            role=role_dir.name,
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
    if entry is not None and not any(tls for _, tls in entry.listeners()):
        return (
            f"cache: hosts: {host} lists no {HTTPS_PORT} under ports, so no TLS "
            f"listener answers the {SCHEME} url"
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


def _segments(path: str) -> list[str]:
    return path.split("/")[1:] if path else []


def _hub_ref(segments: list[str]) -> str:
    resolve = 3 if segments[:1] and segments[0] in HUB_KINDS else 2
    if (
        len(segments) < resolve + 3
        or segments[resolve] != HUB_RESOLVE
        or segments.count(HUB_RESOLVE) != 1
    ):
        return ""
    return segments[resolve + 1]


def _github_raw_ref(segments: list[str]) -> str:
    return segments[2] if len(segments) > 3 else ""


REF_OF: dict[str, Callable[[list[str]], str]] = {
    HUB: _hub_ref,
    GITHUB_RAW: _github_raw_ref,
}


def _revision_problem(revision: str, host: str, segments: list[str]) -> str:
    if not COMMIT.fullmatch(revision):
        return (
            f"revision {revision!r} is not a 40-digit lowercase hex commit; "
            "branches and tags move"
        )
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
    if any(not s.strip(DOT) for s in _segments(parts.path)):
        found.append("url path has an empty or all-dot segment")
    return found


def problems(artefact: Artefact, cache: Declarations) -> list[str]:
    """
    Args:
        artefact: the declaration to check.
        cache: the repositories and hosts, as `declarations` returns them.

    Returns:
        Every way *artefact* breaks the manifest contract; empty when none.
    """
    parts = _split(artefact.url)
    if parts is None:
        found = [f"url {artefact.url!r} is not an absolute {SCHEME} URL"]
        host, segments = "", []
    else:
        found = _url_problems(artefact.url, parts)
        found.append(_repository_problem(artefact.url, parts, cache))
        host, segments = parts.hostname or "", _segments(parts.path)
    if not NAME.fullmatch(artefact.name):
        found.append(f"name {artefact.name!r} does not match {NAME.pattern}")
    found.append(_revision_problem(artefact.revision, host, segments))
    if not SHA256.fullmatch(artefact.sha256):
        found.append("sha256 is not 64 lowercase hex digits")
    if not SIZE.fullmatch(artefact.size):
        found.append(f"bytes {artefact.size!r} is not a positive decimal integer")
    return [problem for problem in found if problem]


def _entry_problems(role: str, name: str, entry: object) -> list[str]:
    if not isinstance(entry, dict):
        return [f"{role}/{name}: the entry is a {type(entry).__name__}, not a mapping"]
    return [
        f"{role}/{name}: key {key!r} is not one of {', '.join(KEYS)}"
        for key in sorted(set(entry) - set(KEYS))
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
        sizes.setdefault(item.sha256, {})[f"{item.role}/{item.name}"] = item.size
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
        every entry key beyond the four, one line each: ``<role>: <problem>``
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


def _base_problem(base: str) -> str:
    if not (base.isascii() and base.isprintable()) or " " in base:
        return "carries whitespace, a control or a non-ASCII character"
    if "?" in base or "#" in base:
        return "carries a query or a fragment"
    if "%" in base:
        return "carries a percent escape"
    if base.endswith(SLASH):
        return "ends in a slash"
    try:
        parts = urlsplit(base)
    except ValueError:
        return "is not a URL"
    if parts.scheme not in BASE_SCHEMES or not parts.hostname:
        return "is not an http or https URL with a host"
    if "@" in parts.netloc:
        return "carries userinfo"
    try:
        valid_port = parts.port != 0
    except ValueError:
        valid_port = False
    return "" if valid_port else "carries a port outside 1 to 65535"


def _checked_base(base: str) -> str:
    if base in ("", SHELL_DEFAULT_BASE):
        return base
    problem = _base_problem(base)
    if problem:
        raise ValueError(f"INFINITO_ARTEFACT_BASE {base!r} {problem}")
    return base


def url_for(url: str, base: str) -> str:
    """
    Args:
        url: the pinned upstream URL.
        base: the value of ``INFINITO_ARTEFACT_BASE``; empty keeps the upstream.

    Returns:
        ``<base>/<host>/<path>``, or *url* itself for an empty base.

    Raises:
        ValueError: *base* is neither empty, ``https:/``, nor an http or https
            URL with a host and a port from 1 to 65535 if any, free of whitespace,
            query, fragment, percent escape, userinfo and a trailing slash.
    """
    if not _checked_base(base):
        return url
    parts = urlsplit(url)
    return f"{base}/{parts.netloc}{parts.path}"


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
    _checked_base(base)
    return {
        item.name: {
            "name": item.name,
            "upstream": item.url,
            "url": url_for(item.url, base),
            "revision": item.revision,
            "sha256": item.sha256,
            "bytes": int(item.size),
            "role": item.role,
        }
        for item in checked()
    }
