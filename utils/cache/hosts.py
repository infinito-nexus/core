"""Collect what the package cache proxies, from ``cache:`` in meta/networks.yml.

The single point of truth for the cache. A role declares the repositories it
needs Nexus to proxy and, where a container must resolve an upstream by name,
the hostname the frontend answers for::

    # roles/<role>/meta/networks.yml
    cache:
      repos:
        raw-example:
          flavor: raw
          upstream: https://example.org/
      hosts:
        example.org:
          repo: raw-example
          read_timeout: 1800s

A repository may serve several hosts and a host may be served by one
repository only; a repository without a host is proxied but never hijacked,
which is how a client that already addresses Nexus directly is served.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_META_NETWORKS
from utils.yaml_bootstrap import BootstrapYamlError, load_block

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"
HTTPS_PORT = 443
HTTP_PORT = 80
CACHE_KEY = "cache"
INDENT = "  "
TRUE = "true"
COMMENT = "#"


def _opens_cache(line: str) -> bool:
    """Whether *line* is the ``cache:`` key itself, comment and all.

    A trailing comment on the key would otherwise make the whole block
    invisible, which reads exactly like a role that declares nothing.
    """
    head = line.split(COMMENT, 1)[0].rstrip()
    return head == f"{CACHE_KEY}:"


@dataclass(frozen=True)
class CachedRepo:
    """One repository Nexus proxies.

    Args:
        name: the Nexus repository name.
        flavor: its repository type, such as ``apt`` or ``raw``.
        upstream: the absolute URL it proxies.
        distribution: the suite an ``apt`` repository serves.
        repodata_depth: the depth a ``yum`` repository indexes.
        mirror: a sibling repository proxying a different host, which the
            frontend falls back to when this one answers 5xx.
        content_max_age: minutes Nexus serves a cached artefact for, where the
            repository needs something other than the stack-wide default.
        role: the role that declared it.
    """

    name: str
    flavor: str
    upstream: str
    distribution: str = ""
    repodata_depth: int = 0
    mirror: str = ""
    content_max_age: str = ""
    role: str = ""


@dataclass(frozen=True)
class CachedHost:
    """One hostname the frontend answers for, in place of its upstream.

    Args:
        host: the hostname a container resolves to the frontend.
        repo: the repository serving its root, when it serves only one.
        paths: the repository behind each path, for a host whose suites live
            side by side, as Debian's do under /debian/ and /debian-security/.
        ports: the frontend ports serving it; apt suites are plain HTTP.
        read_timeout: nginx ``proxy_read_timeout`` where the default is too
            short, as for a multi-gigabyte model download.
        passthrough: the upstream hands out URLs that already carry the
            repository prefix, as npm does for tarballs, so those reach the
            backend unprefixed instead of being prefixed twice into a 404.
        role: the role that declared it.
    """

    host: str
    repo: str = ""
    paths: tuple[tuple[str, str], ...] = ()
    listen: tuple[int, ...] = (HTTPS_PORT,)
    read_timeout: str = ""
    passthrough: bool = False
    role: str = ""

    def routes(self) -> tuple[tuple[str, str], ...]:
        """Return the (path, repository) pairs this host serves."""
        return self.paths or ((("/"), self.repo),)

    def listeners(self) -> tuple[tuple[int, bool], ...]:
        """Return the (port, terminates TLS) pairs this host is served on."""
        return tuple((port, port == HTTPS_PORT) for port in self.listen)

    def scheme(self) -> str:
        """Return the scheme a client addresses this host with."""
        return "https" if HTTPS_PORT in self.listen else "http"

    def path_of(self, repo: str) -> str:
        """Return the path this host serves *repo* under, or the empty string."""
        return next((path for path, name in self.routes() if name == repo), "")


@dataclass(frozen=True)
class Declarations:
    """Everything the roles declare, collected.

    Args:
        repos: the proxied repositories, sorted by name.
        hosts: the hijacked hostnames, sorted by host.
    """

    repos: list[CachedRepo] = field(default_factory=list)
    hosts: list[CachedHost] = field(default_factory=list)


def _cache_block(role_dir: Path) -> dict:
    """Return the ``cache:`` mapping of one role's networks file.

    Only that block is parsed, and only through the bootstrap reader: the env
    generator reaches this module before PyYAML exists, and the rest of the
    file carries constructs (a subnet, for one) the reader rejects.
    """
    try:
        text = read_text(str(role_dir / ROLE_FILE_META_NETWORKS))
    except OSError:
        return {}
    captured: list[str] = []
    inside = False
    for number, line in enumerate(text.splitlines(), start=1):
        if not inside:
            inside = _opens_cache(line)
            continue
        if not line.strip():
            captured.append(line)
            continue
        if not line.startswith(INDENT):
            if line.lstrip().startswith(COMMENT):
                raise BootstrapYamlError(
                    f"{role_dir.name}: line {number} sits at column 0 inside the "
                    f"cache: block. The reader would stop there and silently drop "
                    f"every declaration below it; indent the comment instead."
                )
            break
        captured.append(line[len(INDENT) :])
    if not any(line.strip() for line in captured):
        return {}
    block = load_block("\n".join(captured))
    return block if isinstance(block, dict) else {}


def _section(role_dir: Path, name: str) -> Iterator[tuple[str, dict]]:
    entries = _cache_block(role_dir).get(name)
    if not isinstance(entries, dict):
        return
    for key, entry in entries.items():
        if isinstance(entry, dict):
            yield str(key), entry


def _repos(role_dir: Path) -> Iterator[CachedRepo]:
    for name, entry in _section(role_dir, "repos"):
        yield CachedRepo(
            name=name,
            flavor=str(entry.get("flavor", "raw")),
            upstream=str(entry.get("upstream", "")),
            distribution=str(entry.get("distribution", "")),
            repodata_depth=int(entry.get("repodata_depth", 0)),
            mirror=str(entry.get("mirror", "")),
            content_max_age=str(entry.get("content_max_age", "")),
            role=role_dir.name,
        )


def _hosts(role_dir: Path) -> Iterator[CachedHost]:
    for host, entry in _section(role_dir, "hosts"):
        paths = entry.get("paths") or {}
        yield CachedHost(
            host=host,
            repo=str(entry.get("repo", "")),
            paths=tuple((str(k), str(v)) for k, v in paths.items()),
            listen=tuple(int(port) for port in entry.get("ports") or [HTTPS_PORT]),
            read_timeout=str(entry.get("read_timeout", "")),
            passthrough=str(entry.get("passthrough", "")).lower() == TRUE,
            role=role_dir.name,
        )


def declarations() -> Declarations:
    """Return every declared repository and host.

    Raises:
        ValueError: two roles declare the same repository or host differently,
            or a host names a repository nobody declares.
    """
    repos: dict[str, CachedRepo] = {}
    hosts: dict[str, CachedHost] = {}
    if not ROLES_DIR.is_dir():
        return Declarations()
    for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
        for repo in _repos(role_dir):
            _claim(repos, repo.name, repo, "repository")
        for host in _hosts(role_dir):
            _claim(hosts, host.host, host, "host")
    missing = sorted(
        f"{host.host} (declared by {host.role}) -> {name or '<none>'}"
        for host in hosts.values()
        for _, name in host.routes()
        if name not in repos
    )
    if missing:
        raise ValueError("hosts naming an undeclared repository: " + ", ".join(missing))
    return Declarations(
        repos=[repos[name] for name in sorted(repos)],
        hosts=[hosts[host] for host in sorted(hosts)],
    )


def hosts_serving(repo: str) -> list[CachedHost]:
    """Return every host the frontend answers for on behalf of *repo*."""
    return [
        entry
        for entry in declarations().hosts
        if any(name == repo for _, name in entry.routes())
    ]


def repo_named(name: str) -> CachedRepo | None:
    """Return the declared repository *name*, or None where none declares it."""
    return next((repo for repo in declarations().repos if repo.name == name), None)


def origin_of(repo: CachedRepo) -> str:
    """Return the hostname *repo* proxies, taken from its upstream URL."""
    return urlsplit(repo.upstream).hostname or ""


def host_records() -> dict[str, dict]:
    """Return every declared host as a template-ready record, keyed by host.

    The shape every consumer renders from: the ansible lookups, which then
    apply the inventory, and the dev stack, which does not.
    """
    return {
        entry.host: {
            "host": entry.host,
            "repo": entry.repo or entry.routes()[0][1],
            "routes": [{"path": path, "repo": repo} for path, repo in entry.routes()],
            "listen": [{"port": port, "tls": tls} for port, tls in entry.listeners()],
            "tls": HTTPS_PORT in entry.listen,
            "read_timeout": entry.read_timeout,
            "passthrough": entry.passthrough,
            "role": entry.role,
        }
        for entry in declarations().hosts
    }


def repo_records() -> dict[str, dict]:
    """Return every declared repository as a record, keyed by name."""
    return {
        repo.name: {
            "name": repo.name,
            "flavor": repo.flavor,
            "upstream": repo.upstream,
            "distribution": repo.distribution,
            "repodata_depth": repo.repodata_depth,
            "mirror": repo.mirror,
            "content_max_age": repo.content_max_age,
            "role": repo.role,
        }
        for repo in declarations().repos
    }


def _claim(seen: dict, key: str, found, kind: str) -> None:
    first = seen.setdefault(key, found)
    if first != found:
        raise ValueError(
            f"{kind} {key} is declared by {first.role} and again, differently, "
            f"by {found.role}"
        )
