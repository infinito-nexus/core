"""Resolve version pins that declare their own upstream source.

The Docker updater watches ``image`` plus ``version``, the repository updater
``repository`` plus ``ref``. A pin outside both - an ``app_version``, a
``release``, a tag in a registry neither updater speaks - declares where its
upstream lives::

    stalwart:
      webui_version: "v1.0.5"
      update:
        key: webui_version
        type: git_tags
        repository: https://github.com/stalwartlabs/webui.git

``key`` names the pinned key and defaults to ``version``; an entity with
several pins declares a list of such blocks. The types are
``git_tags`` (repository), ``registry_tags`` (image), ``npm`` (package),
``http_regex`` (one url or several, pattern, optionally a template over the
pattern's named groups) and ``script`` (path, run with the current version and
printing the latest one). A pin whose asset is fetched by digest names its
companion checksum beside the type; see :mod:`utils.update.checksum`.

An addon in ``meta/addons/<id>.yml`` declares the same fields in its
``update:`` block, beside ``monitored``, ``catalog`` and ``upstream_id``. A
monitored addon of the ``github-releases`` catalog needs no ``type``: its
``upstream_id`` already names the repository whose tags are its versions. An
addon's ``config.archive`` URL carries the pinned version and moves with it.
"""

from __future__ import annotations

import json
import re
import subprocess
import urllib.error
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.update import checksum
from utils.update.addons import GITHUB_RELEASES_CATALOG, iter_addon_files
from utils.update.base import (
    captured_versions,
    is_maintained,
    is_semver,
    newer_version,
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
from utils.update.fetch import TIMEOUT_SECONDS, documents, get
from utils.update.pins import archive_index, key_line, top_level_line
from utils.update.repository import git_ls_remote_tags

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

NOCHECK_MARKER = "version-source"
UNWATCHED_MARKER = "unwatched-version"
UPDATE_KEY = "update"
DEFAULT_KEY = "version"
TYPES = ("git_tags", "registry_tags", "npm", "http_regex", "script")


@dataclass(frozen=True)
class VersionSourceEntry:
    """One pin and the upstream it declares.

    Args:
        role: role that carries the pin.
        entity: service entity in ``meta/services.yml``, or the addon id.
        key: pinned key.
        current: pinned version.
        source: the ``update:`` block.
        config_path: file that carries the pin.
        line: 1-indexed line of the pin.
        addon: whether the pin sits in ``meta/addons/<id>.yml``.
    """

    role: str
    entity: str
    key: str
    current: str
    source: dict[str, Any]
    config_path: Path
    line: int
    addon: bool = False


@dataclass(frozen=True)
class VersionSourceUpdate:
    entry: VersionSourceEntry
    latest: str


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
        payload = json.loads(get(url))
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
        return list(json.loads(get(url)).get("tags") or [])
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
        token = json.loads(get(f"{realm}?{query}")).get("token", "")
        payload = get(url, {"Authorization": f"Bearer {token}"})
        return list(json.loads(payload).get("tags") or [])
    except (OSError, ValueError):
        return []


def npm_versions(package: str) -> list[str]:
    """Return every published version of an npm *package*."""
    try:
        payload = json.loads(get(f"https://registry.npmjs.org/{package}"))
    except (OSError, ValueError):
        return []
    return list((payload.get("versions") or {}).keys())


def http_regex_versions(
    urls: str | list[str], pattern: str, template: str = ""
) -> list[str]:
    """Return every version *pattern* names in the documents at *urls*."""
    try:
        body = documents(urls)
    except OSError:
        return []
    return captured_versions(body, pattern, template)


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
        found = http_regex_versions(
            source["url"],
            str(source["pattern"]),
            str(source.get("template", "")),
        )
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


def _archive(spec: Any) -> str:
    """Return the ``config.archive`` URL of an addon, or an empty string."""
    config = spec.get("config") if isinstance(spec, dict) else None
    return str(config.get("archive", "")) if isinstance(config, dict) else ""


def addon_sources(spec: Any) -> list[dict[str, Any]]:
    """Return the version sources an addon declares.

    Args:
        spec: root mapping of a ``meta/addons/<id>.yml`` file.
    """
    declared = spec.get(UPDATE_KEY) if isinstance(spec, dict) else None
    if not isinstance(declared, dict):
        return []
    if "type" in declared:
        return [declared]
    if (
        declared.get("monitored")
        and declared.get("catalog") == GITHUB_RELEASES_CATALOG
        and declared.get("upstream_id")
    ):
        repository = f"https://github.com/{declared['upstream_id']}.git"
        return [{**declared, "type": "git_tags", "repository": repository}]
    return []


def _monitored_pin(spec: Any) -> str:
    """Return the version a monitored addon pins, or an empty string."""
    declared = spec.get(UPDATE_KEY) if isinstance(spec, dict) else None
    if not isinstance(declared, dict) or not declared.get("monitored"):
        return ""
    return str(spec.get(DEFAULT_KEY) or "").strip()


def _not_semver(label: str, pinned: Any) -> str:
    return (
        f"{label}: '{pinned}' is not a semver, so no upstream version orders "
        "above it and the pin never moves"
    )


def _declaration_problems(
    label: str, config: dict[str, Any], source: Any, owner: str
) -> list[str]:
    """Return what keeps one ``update:`` block from resolving.

    Args:
        label: ``<role>/<entity>`` as it appears in the message.
        config: mapping that carries the pin.
        source: the ``update:`` block.
        owner: what ``config`` is, ``entity`` or ``addon``.
    """
    if not isinstance(source, dict):
        return [f"{label}: update entry is not a mapping"]
    problems: list[str] = []
    key = str(source.get("key", DEFAULT_KEY))
    if key not in config:
        problems.append(f"{label}: update.key '{key}' names no key of the {owner}")
    elif not is_semver(str(config[key])):
        problems.append(_not_semver(f"{label}.{key}", config[key]))
    if source.get("type") not in TYPES:
        problems.append(
            f"{label}.{key}: unknown update.type "
            f"'{source.get('type')}', expected one of {', '.join(TYPES)}"
        )
    problems += checksum.problems(label, key, config, source)
    archive = _archive(config) if owner == "addon" else ""
    if archive and str(config.get(key, "")) not in archive:
        problems.append(
            f"{label}.{key}: config.archive does not carry the pinned version, "
            "so a bump would move only one of the two"
        )
    return problems


def invalid_declarations(repo_root: Path) -> list[str]:
    """Return one message per ``update:`` block that cannot be resolved.

    A block naming a key the entity does not carry, a type the resolver does
    not know, or a pin that is not a semver would otherwise move nothing and
    say nothing. A monitored addon the resolver does not read is held to the
    same semver rule.

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
                problems += _declaration_problems(
                    f"{role}/{entity}", config, source, "entity"
                )
    for role, addon_path in iter_addon_files(repo_root / "roles"):
        spec = load_yaml(str(addon_path))
        label = f"{role}/addons/{addon_path.stem}"
        sources = addon_sources(spec)
        for source in sources:
            problems += _declaration_problems(label, spec, source, "addon")
        pinned = "" if sources else _monitored_pin(spec)
        if pinned and not is_semver(pinned):
            problems.append(_not_semver(f"{label}.{DEFAULT_KEY}", pinned))
    return problems


def _addon_entries(repo_root: Path) -> list[VersionSourceEntry]:
    roles_root = repo_root / "roles"
    entries: list[VersionSourceEntry] = []
    for role, addon_path in iter_addon_files(roles_root):
        if not is_maintained(roles_root, role):
            continue
        spec = load_yaml(str(addon_path))
        lines = read_text(str(addon_path)).splitlines()
        for source in addon_sources(spec):
            key = str(source.get("key", DEFAULT_KEY))
            current = str(spec.get(key, "")).strip()
            line = top_level_line(lines, key)
            if not current or line is None:
                continue
            if any(
                is_suppressed_at(lines, line, marker)
                for marker in (NOCHECK_MARKER, UNWATCHED_MARKER)
            ):
                continue
            entries.append(
                VersionSourceEntry(
                    role=role,
                    entity=addon_path.stem,
                    key=key,
                    current=current,
                    source=source,
                    config_path=addon_path,
                    line=line,
                    addon=True,
                )
            )
    return entries


def collect_entries(repo_root: Path) -> list[VersionSourceEntry]:
    """Return every declared version source that is not suppressed."""
    roles_root = repo_root / "roles"
    entries: list[VersionSourceEntry] = []
    for config_path in sorted(roles_root.glob(f"*/{ROLE_FILE_META_SERVICES}")):
        role = config_path.parts[-3]
        if not is_maintained(roles_root, role):
            continue
        lines = read_text(str(config_path)).splitlines()
        for entity, config in (load_yaml(str(config_path)) or {}).items():
            declared = config.get(UPDATE_KEY) if isinstance(config, dict) else None
            sources = declared if isinstance(declared, list) else [declared]
            for source in sources:
                if not isinstance(source, dict):
                    continue
                key = str(source.get("key", DEFAULT_KEY))
                current = str(config.get(key, "")).strip()
                line = key_line(lines, str(entity), key)
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
    return entries + _addon_entries(repo_root)


def outdated(
    entries: Iterable[VersionSourceEntry], repo_root: Path
) -> list[VersionSourceUpdate]:
    """Return one update per entry whose source offers a newer version."""
    updates: list[VersionSourceUpdate] = []
    for entry in entries:
        newest = newer_version(
            entry.current,
            candidates(entry, repo_root),
            assembled=bool(entry.source.get("template")),
        )
        if newest:
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
        archive = archive_index(lines) if update.entry.addon else None
        if archive is not None:
            lines[archive] = lines[archive].replace(
                update.entry.current, update.latest, 1
            )
        checksum.rewrite(
            lines,
            "" if update.entry.addon else update.entry.entity,
            update.entry.source,
            update.latest,
        )
        path.write_text("".join(lines), encoding="utf-8")
        if path not in changed:
            changed.append(path)
    return changed
