from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlsplit

from utils.cache.records import mirrors, upstream

if TYPE_CHECKING:
    from utils.cache.hosts import Declarations

    Targets = dict[tuple[str, str], "Target"]

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


def apt_targets(nexus: str, ubuntu_mirrors: str, declared: Declarations) -> Targets:
    """Map every archive and suite the package cache serves to its Nexus repository.

    Args:
        nexus: base URL the host reaches the package cache's Nexus at.
        ubuntu_mirrors: ``INFINITO_APT_UBUNTU_MIRRORS``, which the Ubuntu
            upstream placeholders resolve from; empty reads it from the
            environment with ``default.env`` behind it.
        declared: the ``cache:`` declarations.

    Returns:
        ``{(archive, suite): Target}`` for every ``apt`` repository no other
        one names as its mirror. Its archives are the URLs it and its mirror
        proxy and the URLs the frontend answers for on its behalf, without
        scheme; ``secure`` tells whether every upstream it fetches from is
        HTTPS.
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
            targets[(found[1], repo.distribution)] = target
    return targets


def _route(targets: Targets, uri: str, suite: str) -> str:
    found = archive_of(uri)
    target = targets.get((found[1], suite)) if found else None
    if target is None or (found[0] == SECURE and not target.secure):
        return ""
    return target.url


def _insecure(options: str) -> bool:
    pairs = (unquote(word.replace('"', "")).partition("=") for word in options.split())
    return any(
        name.lower() in INSECURE_FIELDS and value.lower() not in FALSE
        for name, _, value in pairs
    )


def list_file(text: str, targets: Targets) -> tuple[str, list[str]]:
    """Point the one-line apt entries the package cache serves at Nexus.

    Args:
        text: a ``sources.list`` style file.
        targets: what ``apt_targets`` returns.

    Returns:
        *text* with a copy of every ``deb`` entry whose archive and suite the
        cache serves inserted before it, its URI replaced by the Nexus
        repository and every option kept, and the copies. An entry that sets
        ``trusted``, ``allow-insecure``, ``allow-weak`` or
        ``allow-downgrade-to-insecure`` to anything but a false value, or
        reaches its archive over HTTPS while the cache fetches it over HTTP,
        gets no copy.
    """
    out: list[str] = []
    added: list[str] = []
    for line in text.splitlines(keepends=True):
        match = ONE_LINE.match(line)
        url = ""
        if match and not _insecure(match["options"] or ""):
            url = _route(targets, match["uri"], match["suite"])
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


def _stanzas(block: list[str], targets: Targets) -> list[str]:
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
    routed = {
        url: suite
        for uri in values.get("uris", [])
        for suite in values.get("suites", [])
        if (url := _route(targets, uri, suite))
    }
    stanzas = []
    for url, suite in routed.items():
        replaced = {"types": "deb", "uris": url, "suites": suite}
        lines: list[str] = []
        for name, raw in fields:
            key = name.lower()
            lines.extend([f"{name}: {replaced[key]}\n"] if key in replaced else raw)
        if not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        stanzas.append("".join([*lines, "\n"]))
    return stanzas


def sources_file(text: str, targets: Targets) -> tuple[str, list[str]]:
    """Point the deb822 apt stanzas the package cache serves at Nexus.

    Args:
        text: a ``.sources`` file.
        targets: what ``apt_targets`` returns.

    Returns:
        *text* with one stanza per Nexus repository a ``deb`` stanza reaches
        inserted before it, holding ``Types: deb``, that repository as
        ``URIs`` and the suite it serves as ``Suites``, every other field
        copied verbatim, and those stanzas. A stanza that is disabled, or sets
        ``Trusted``, ``Allow-Insecure``, ``Allow-Weak`` or
        ``Allow-Downgrade-To-Insecure`` to anything but a false value, gets
        none, as does an HTTPS URI the cache fetches over HTTP.
    """
    out: list[str] = []
    added: list[str] = []
    block: list[str] = []
    for line in [*text.splitlines(keepends=True), ""]:
        if line.strip():
            block.append(line)
            continue
        stanzas = _stanzas(block, targets) if block else []
        out.extend([*stanzas, *block, line])
        added.extend(stanzas)
        block = []
    return "".join(out), added
