from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlsplit

from utils.cache.records import mirrors, upstream

if TYPE_CHECKING:
    from utils.cache.hosts import Declarations

    Targets = dict[str, dict[str, "Target"]]
    Claims = dict[tuple[str, str], str]

APT_FLAVOR = "apt"
SECURE = "https"
SCHEMES = frozenset({"http", SECURE})
INSECURE_FIELDS = (
    "trusted",
    "allow-insecure",
    "allow-weak",
    "allow-downgrade-to-insecure",
)
FALSE = frozenset({"no", "false", "without", "off", "disable", "0"})
ONE_LINE = re.compile(
    r"^\s*deb\s+(?:\[(?P<options>[^\]]*)\]\s+)?(?P<uri>\S+)\s+(?P<suite>\S+)"
)
ENTRY = re.compile(r"^\s*deb(?:-src)?\s+(?:\[[^\]]*\]\s+)?(?P<uri>\S+)")
FIELD = re.compile(r"^(?P<name>[A-Za-z][A-Za-z0-9-]*):(?P<value>.*)", re.DOTALL)


@dataclass(frozen=True)
class Target:
    url: str
    secure: bool


def archive_of(uri: str) -> tuple[str, str] | None:
    """Return the scheme and the archive an apt URI names.

    Args:
        uri: an apt source URI.

    Returns:
        ``(scheme, "<host><path>")`` without a trailing slash, or None for
        anything but an http(s) URL with a host.
    """
    try:
        parts = urlsplit(uri)
        host = parts.hostname
    except ValueError:
        return None
    if parts.scheme not in SCHEMES or not host:
        return None
    return parts.scheme, f"{host}{parts.path.rstrip('/')}"


def pocket(suite: str) -> str:
    """Return the pocket an apt suite names after its codename.

    Args:
        suite: a suite such as ``trixie-security``.

    Returns:
        ``security`` for ``trixie-security``, the empty string for ``trixie``.
    """
    return suite.partition("-")[2]


def apt_targets(nexus: str, ubuntu_mirrors: str, declared: Declarations) -> Targets:
    """Map every archive the package cache proxies to its Nexus repositories.

    Args:
        nexus: base URL the host reaches the package cache's Nexus at.
        ubuntu_mirrors: ``INFINITO_APT_UBUNTU_MIRRORS``, which the Ubuntu
            upstream placeholders resolve from; empty reads it from the
            environment with ``default.env`` behind it.
        declared: the ``cache:`` declarations.

    Returns:
        ``{archive: {pocket: Target}}`` for every ``apt`` repository no other
        one names as its mirror, under the pocket of its distribution. Its
        archives are the URLs it and its mirror proxy and the URLs the
        frontend answers for on its behalf, without scheme; ``secure`` tells
        whether every upstream it fetches from is HTTPS.
    """
    repos = {repo.name: repo for repo in declared.repos}
    siblings = {repo.mirror for repo in declared.repos if repo.mirror}
    resolved = mirrors(ubuntu_mirrors)
    targets: Targets = {}
    for repo in declared.repos:
        if repo.flavor != APT_FLAVOR or repo.name in siblings:
            continue
        sources = [
            upstream(r.upstream, resolved) for r in (repo, repos.get(repo.mirror)) if r
        ]
        target = Target(
            f"{nexus.rstrip('/')}/repository/{repo.name}/",
            all(urlsplit(url).scheme == SECURE for url in sources),
        )
        served = [
            f"{host.scheme()}://{host.host}{host.path_of(repo.name)}"
            for host in declared.hosts
            if host.path_of(repo.name)
        ]
        for found in filter(None, map(archive_of, sources + served)):
            archive = targets.setdefault(found[1], {})
            archive.setdefault(pocket(repo.distribution), target)
    return targets


def _pockets(targets: Targets, archive: str) -> dict[str, Target]:
    if archive in targets:
        return targets[archive]
    host, _, path = archive.partition("/")
    parents = [
        key
        for key in targets
        if key.partition("/")[2] == path and host.endswith(f".{key.partition('/')[0]}")
    ]
    return targets[max(parents, key=len)] if parents else {}


def _route(targets: Targets, uri: str, suite: str, claims: Claims) -> str:
    found = archive_of(uri)
    if found is None:
        return ""
    pockets = _pockets(targets, found[1])
    target = pockets.get(pocket(suite)) or pockets.get("")
    if target is None or (found[0] == SECURE and not target.secure):
        return ""
    if claims.setdefault((target.url, suite), found[1]) != found[1]:
        return ""
    return target.url


def _insecure(options: str) -> bool:
    pairs = (unquote(word.replace('"', "")).partition("=") for word in options.split())
    return any(
        name.lower() in INSECURE_FIELDS and value.lower() not in FALSE
        for name, _, value in pairs
    )


def list_file(text: str, targets: Targets, claims: Claims) -> tuple[str, list[str]]:
    """Point the one-line apt entries the package cache serves at Nexus.

    Args:
        text: a ``sources.list`` style file.
        targets: what ``apt_targets`` returns.
        claims: the archive each Nexus repository and suite got its first
            copy from, shared by every file of one host and filled in here.

    Returns:
        *text* with a copy of every ``deb`` entry whose archive the cache
        proxies, or whose host is a subdomain of one with the same path,
        inserted before it, its URI replaced by the repository serving its
        suite's pocket, else the archive's release repository, and every
        option kept, and the copies. An entry gets no copy where it sets
        ``trusted``, ``allow-insecure``, ``allow-weak`` or
        ``allow-downgrade-to-insecure`` to anything but a false value,
        reaches its archive over HTTPS while the cache fetches it over HTTP,
        or names a repository and suite already copied from another archive.
    """
    out: list[str] = []
    added: list[str] = []
    for line in text.splitlines(keepends=True):
        match = ONE_LINE.match(line)
        url = ""
        if match and not _insecure(match["options"] or ""):
            url = _route(targets, match["uri"], match["suite"], claims)
        if url:
            copy = line[: match.start("uri")] + url + line[match.end("uri") :]
            copy = copy if copy.endswith("\n") else f"{copy}\n"
            out.append(copy)
            added.append(copy)
        out.append(line)
    return "".join(out), added


def _fields(block: list[str]) -> list[tuple[str, list[str]]]:
    fields: list[tuple[str, list[str]]] = []
    for line in block:
        if line.startswith("#"):
            continue
        if line[0] in " \t" and fields:
            fields[-1][1].append(line)
        elif match := FIELD.match(line):
            fields.append((match["name"], [line]))
    return fields


def _values(lines: list[str]) -> list[str]:
    return (FIELD.match(lines[0])["value"] + "".join(lines[1:])).split()


def _flag(values: dict[str, list[str]], name: str) -> str:
    return " ".join(values.get(name, [])).lower()


def _stanzas(block: list[str], targets: Targets, claims: Claims) -> list[str]:
    fields = _fields(block)
    values = {name.lower(): _values(lines) for name, lines in fields}
    if "deb" not in values.get("types", []) or _flag(values, "enabled") in FALSE:
        return []
    if any(
        name.lower() in INSECURE_FIELDS
        and " ".join(_values(lines)).lower() not in FALSE
        for name, lines in fields
    ):
        return []
    routed: dict[str, list[str]] = {}
    for uri in values.get("uris", []):
        for suite in values.get("suites", []):
            url = _route(targets, uri, suite, claims)
            if url and suite not in routed.setdefault(url, []):
                routed[url].append(suite)
    stanzas = []
    for url, suites in routed.items():
        replaced = {"types": "deb", "uris": url, "suites": " ".join(suites)}
        lines: list[str] = []
        for name, raw in fields:
            key = name.lower()
            lines.extend([f"{name}: {replaced[key]}\n"] if key in replaced else raw)
        if not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        stanzas.append("".join([*lines, "\n"]))
    return stanzas


def sources_file(text: str, targets: Targets, claims: Claims) -> tuple[str, list[str]]:
    """Point the deb822 apt stanzas the package cache serves at Nexus.

    Args:
        text: a ``.sources`` file.
        targets: what ``apt_targets`` returns.
        claims: the archive each Nexus repository and suite got its first
            copy from, shared by every file of one host and filled in here.

    Returns:
        *text* with one stanza per Nexus repository a ``deb`` stanza reaches
        inserted before it, holding ``Types: deb``, that repository as
        ``URIs`` and the suites it serves there as ``Suites``, every other
        field copied verbatim, and those stanzas. A stanza that is disabled, or
        sets ``Trusted``, ``Allow-Insecure``, ``Allow-Weak`` or
        ``Allow-Downgrade-To-Insecure`` to anything but a false value, gets
        none; a suite gets none where the stanza reaches its archive over
        HTTPS while the cache fetches it over HTTP, or where its repository
        and suite were copied from another archive.
    """
    out: list[str] = []
    added: list[str] = []
    block: list[str] = []
    for line in [*text.splitlines(keepends=True), ""]:
        if line.strip():
            block.append(line)
            continue
        stanzas = _stanzas(block, targets, claims) if block else []
        out.extend([*stanzas, *block, line])
        added.extend(stanzas)
        block = []
    return "".join(out), added


def _copied(uri: str, copies: frozenset[str]) -> bool:
    return f"{uri.rstrip('/')}/" in copies


def strip_list(text: str, copies: frozenset[str]) -> str:
    """Drop the one-line entries a sync pointed at Nexus.

    Args:
        text: a ``sources.list`` style file.
        copies: the repository URLs that sync could point a copy at.

    Returns:
        *text* without every ``deb`` and ``deb-src`` line whose URI is one of
        *copies*.
    """
    return "".join(
        line
        for line in text.splitlines(keepends=True)
        if not ((match := ENTRY.match(line)) and _copied(match["uri"], copies))
    )


def _without(block: list[str], copies: frozenset[str]) -> list[str]:
    raw = next((lines for name, lines in _fields(block) if name.lower() == "uris"), [])
    uris = _values(raw) if raw else []
    kept = [uri for uri in uris if not _copied(uri, copies)]
    if kept == uris:
        return block
    if not kept:
        return [line for line in block if line.startswith("#")]
    field = f"{FIELD.match(raw[0])['name']}: {' '.join(kept)}\n"
    out: list[str] = []
    inside = False
    for line in block:
        if line.startswith("#"):
            out.append(line)
        elif line == raw[0]:
            inside = True
            out.append(field)
        elif not (inside and line[0] in " \t"):
            inside = False
            out.append(line)
    return out


def strip_sources(text: str, copies: frozenset[str]) -> str:
    """Drop the URIs a sync pointed at Nexus from every deb822 stanza.

    Args:
        text: a ``.sources`` file.
        copies: the repository URLs that sync could point a copy at.

    Returns:
        *text* without every URI that is one of *copies*, and without every
        stanza left with no URI, together with the blank line that separated
        it; the comments of such a stanza stay.
    """
    out: list[str] = []
    block: list[str] = []
    for line in [*text.splitlines(keepends=True), ""]:
        if line.strip():
            block.append(line)
            continue
        kept = _without(block, copies)
        if kept or not block:
            out.extend([*kept, line])
        elif not line and out and not out[-1].strip():
            out.pop()
        block = []
    return "".join(out)
