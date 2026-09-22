"""Resolve version pins that declare their own upstream source.

The Docker updater watches ``image`` plus ``version``, the repository updater
``repository`` plus ``ref``. A pin outside both - an ``app_version``, a
``release``, a tag in a registry neither updater speaks - declares where its
upstream lives::

    lmstudio:
      app_version: 0.0.25-1
      update:
        key: app_version
        type: http_regex
        url: https://lmstudio.ai/install.sh
        pattern: 'APP_VERSION="([0-9][0-9.-]*)"'

``key`` names the pinned key and defaults to ``version``; an entity with
several pins declares a list of such blocks. The types are
``git_tags`` (repository), ``registry_tags`` (image), ``npm`` (package),
``http_regex`` (url, pattern) and ``script`` (path, run with the current
version and printing the latest one).
"""

from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.update.base import (
    latest_semver,
    version_depth,
    version_flavor,
    version_key,
)
from utils.update.docker import (
    dockerhub_repo,
    fetch_dockerhub_tags,
    fetch_ghcr_tags,
    fetch_mcr_tags,
    is_dockerhub,
    is_ghcr,
    is_mcr,
)
from utils.update.repository import git_ls_remote_tags

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

NOCHECK_MARKER = "version-source"
UPDATE_KEY = "update"
DEFAULT_KEY = "version"
TIMEOUT_SECONDS = 30
TYPES = ("git_tags", "registry_tags", "npm", "http_regex", "script")
USER_AGENT = "infinito-nexus-version-source"


@dataclass(frozen=True)
class VersionSourceEntry:
    role: str
    entity: str
    key: str
    current: str
    source: dict[str, Any]
    config_path: Path
    line: int


@dataclass(frozen=True)
class VersionSourceUpdate:
    entry: VersionSourceEntry
    latest: str


def _get(url: str, headers: dict[str, str] | None = None) -> bytes:
    request = urllib.request.Request(  # noqa: S310 - https URL of a declared version source
        url, headers={"User-Agent": USER_AGENT, **(headers or {})}
    )
    with urllib.request.urlopen(  # noqa: S310 - https URL of a declared version source
        request, timeout=TIMEOUT_SECONDS
    ) as response:
        return response.read()


def dockerhub_named_tags(image: str, match: str) -> list[str]:
    """Return the Docker Hub tags of *image* whose name contains *match*.

    Args:
        image: Docker Hub reference.
        match: substring the registry filters on, reaching tags beyond the
            first pages of the unfiltered listing.
    """
    query = urlencode({"name": match, "page_size": 100})
    url = f"https://hub.docker.com/v2/repositories/{dockerhub_repo(image)}/tags?{query}"
    try:
        payload = json.loads(_get(url))
    except (OSError, ValueError):
        return []
    return [str(result["name"]) for result in payload.get("results") or []]


def registry_v2_tags(image: str, match: str = "") -> list[str]:
    """Return the tags of *image* from its registry's v2 API.

    Args:
        image: reference including the registry host, e.g.
            ``gcr.io/cadvisor/cadvisor``.
        match: when set and the registry can filter server-side, the
            substring every returned tag carries.
    """
    if is_dockerhub(image):
        return (
            dockerhub_named_tags(image, match) if match else fetch_dockerhub_tags(image)
        )
    if is_ghcr(image):
        return fetch_ghcr_tags(image)
    if is_mcr(image):
        return fetch_mcr_tags(image)
    host, _, repository = image.partition("/")
    url = f"https://{host}/v2/{repository}/tags/list"
    try:
        return list(json.loads(_get(url)).get("tags") or [])
    except urllib.error.HTTPError as error:
        if error.code != 401:
            return []
        challenge = error.headers.get("WWW-Authenticate", "")
    except (OSError, ValueError):
        return []
    fields = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
    realm = fields.pop("realm", "")
    if not realm:
        return []
    query = "&".join(f"{name}={value}" for name, value in fields.items())
    try:
        token = json.loads(_get(f"{realm}?{query}")).get("token", "")
        payload = _get(url, {"Authorization": f"Bearer {token}"})
        return list(json.loads(payload).get("tags") or [])
    except (OSError, ValueError):
        return []


def npm_versions(package: str) -> list[str]:
    """Return every published version of an npm *package*."""
    try:
        payload = json.loads(_get(f"https://registry.npmjs.org/{package}"))
    except (OSError, ValueError):
        return []
    return list((payload.get("versions") or {}).keys())


def http_regex_versions(url: str, pattern: str) -> list[str]:
    """Return every capture of *pattern* in the body of *url*."""
    try:
        body = _get(url).decode("utf-8", "replace")
    except OSError:
        return []
    return [match.group(1) for match in re.finditer(pattern, body)]


def script_versions(repo_root: Path, role: str, path: str, current: str) -> list[str]:
    """Return what a role-local updater prints for its pin.

    Args:
        repo_root: repository root.
        role: role the script belongs to.
        path: role-relative path of the script.
        current: the version currently pinned, passed as the first argument.
    """
    script = repo_root / "roles" / role / path
    try:
        proc = subprocess.run(
            [str(script), current],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return proc.stdout.split() if proc.returncode == 0 else []


def candidates(entry: VersionSourceEntry, repo_root: Path) -> list[str]:
    """Return every upstream version the entry's declared source offers.

    ``match`` keeps only the versions carrying that prefix, and ``strip``
    removes it again, so a pin without the upstream's ``v`` stays without it.
    """
    source = entry.source
    kind = source.get("type")
    match = str(source.get("match", ""))
    if kind == "git_tags":
        found = git_ls_remote_tags(str(source["repository"]))
    elif kind == "registry_tags":
        found = registry_v2_tags(str(source["image"]), match)
    elif kind == "npm":
        found = npm_versions(str(source["package"]))
    elif kind == "http_regex":
        found = http_regex_versions(str(source["url"]), str(source["pattern"]))
    elif kind == "script":
        found = script_versions(
            repo_root, entry.role, str(source["path"]), entry.current
        )
    else:
        return []
    if match:
        found = [version for version in found if version.startswith(match)]
        if source.get("strip"):
            found = [version.removeprefix(match) for version in found]
    return found


def _key_line(lines: list[str], entity: str, key: str) -> int | None:
    """Return the 1-indexed line of ``key`` inside the block of ``entity``."""
    inside = False
    for number, line in enumerate(lines, start=1):
        if re.match(rf"^{re.escape(entity)}\s*:", line):
            inside = True
            continue
        if inside and line and not line[0].isspace():
            inside = False
        if inside and re.match(rf"^\s+{re.escape(key)}\s*:", line):
            return number
    return None


def invalid_declarations(repo_root: Path) -> list[str]:
    """Return one message per ``update:`` block that cannot be resolved.

    A block naming a key the entity does not carry, or a type the resolver
    does not know, would otherwise pin nothing and say nothing.

    Args:
        repo_root: repository root.
    """
    problems: list[str] = []
    for config_path in sorted(
        (repo_root / "roles").glob(f"*/{ROLE_FILE_META_SERVICES}")
    ):
        role = config_path.parts[-3]
        for entity, config in (load_yaml(str(config_path)) or {}).items():
            declared = config.get(UPDATE_KEY) if isinstance(config, dict) else None
            if declared is None:
                continue
            sources = declared if isinstance(declared, list) else [declared]
            for source in sources:
                if not isinstance(source, dict):
                    problems.append(f"{role}/{entity}: update entry is not a mapping")
                    continue
                key = str(source.get("key", DEFAULT_KEY))
                if key not in config:
                    problems.append(
                        f"{role}/{entity}: update.key '{key}' names no key of the entity"
                    )
                if source.get("type") not in TYPES:
                    problems.append(
                        f"{role}/{entity}.{key}: unknown update.type "
                        f"'{source.get('type')}', expected one of {', '.join(TYPES)}"
                    )
    return problems


def collect_entries(repo_root: Path) -> list[VersionSourceEntry]:
    """Return every declared version source that is not suppressed."""
    entries: list[VersionSourceEntry] = []
    for config_path in sorted(
        (repo_root / "roles").glob(f"*/{ROLE_FILE_META_SERVICES}")
    ):
        role = config_path.parts[-3]
        lines = read_text(str(config_path)).splitlines()
        for entity, config in (load_yaml(str(config_path)) or {}).items():
            declared = config.get(UPDATE_KEY) if isinstance(config, dict) else None
            sources = declared if isinstance(declared, list) else [declared]
            for source in sources:
                if not isinstance(source, dict):
                    continue
                key = str(source.get("key", DEFAULT_KEY))
                current = str(config.get(key, "")).strip()
                line = _key_line(lines, str(entity), key)
                if not current or line is None:
                    continue
                if is_suppressed_at(lines, line, NOCHECK_MARKER):
                    continue
                entries.append(
                    VersionSourceEntry(
                        role=role,
                        entity=str(entity),
                        key=key,
                        current=current,
                        source=source,
                        config_path=config_path,
                        line=line,
                    )
                )
    return entries


def outdated(
    entries: Iterable[VersionSourceEntry], repo_root: Path
) -> list[VersionSourceUpdate]:
    """Return one update per entry whose source offers a newer version."""
    updates: list[VersionSourceUpdate] = []
    for entry in entries:
        newest = latest_semver(
            candidates(entry, repo_root),
            version_depth(entry.current),
            version_flavor(entry.current),
        )
        if newest and version_key(entry.current) < version_key(newest):
            updates.append(VersionSourceUpdate(entry=entry, latest=newest))
    return updates


def find_outdated_updates(repo_root: Path) -> list[VersionSourceUpdate]:
    """Return every declared source that moved ahead of its pin."""
    return outdated(collect_entries(repo_root), repo_root)


def apply_updates(updates: Iterable[VersionSourceUpdate]) -> list[Path]:
    """Rewrite every pin to its newer version and return the changed files."""
    changed: list[Path] = []
    for update in updates:
        path = update.entry.config_path
        lines = path.read_text(  # nocheck: cache-read  read-modify-write: a cached read serves the pre-write content when two pins of one file are bumped in the same run
            encoding="utf-8"
        ).splitlines(keepends=True)
        index = update.entry.line - 1
        lines[index] = lines[index].replace(update.entry.current, update.latest, 1)
        path.write_text("".join(lines), encoding="utf-8")
        if path not in changed:
            changed.append(path)
    return changed
