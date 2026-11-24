"""Detect and rewrite outdated Docker image `version:` tags in
`roles/*/meta/services.yml`, and the tags of the `image:` literals in the
repository's own compose files (:func:`compose_files`).

Counterpart to :mod:`utils.update.repository` (which handles git refs).
Both share the semver primitives in :mod:`utils.update.base`; this
module owns the bump selection and the YAML walker that rewrites the
matching ``version:`` line; registry lookups live in
:mod:`utils.update.docker.tags`, compose files in
:mod:`utils.update.docker.compose`.

Suppress a check by placing ``# nocheck: docker-version`` on the line
directly above the ``version:`` key, or above a compose service's ``image:``.

A ``version`` that names its own upstream in an ``update:`` block belongs to
:mod:`utils.update.source` and is not collected here.
"""

from __future__ import annotations

import concurrent.futures
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

import yaml

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.docker.image.discovery import (
    RUNNER_ROLE,
    ImageRef,
    iter_compose_images,
    iter_role_images,
)
from utils.docker.image.ref import is_dockerhub
from utils.docker.registry import fetch_registry_tags
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.security.suppressions import drop_image_tag_entries
from utils.update.base import (
    declares_source,
    is_maintained,
    is_semver,
    latest_semver,
    resolve_max_fetch_workers,
    version_depth,
    version_flavor,
    version_key,
)
from utils.update.docker.compose import (
    _compose_image_lines,
    compose_files,
    suppressed_compose_services,
    update_compose_images,
)
from utils.update.docker.tags import (
    fetch_dockerhub_tags,
    fetch_ghcr_tags,
    fetch_mcr_tags,
    is_ghcr,
    is_mcr,
    is_supported_registry,
)
from utils.update.follow import followed_tags

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

_KEY_RE = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z0-9_-]+):(?P<rest>.*)$")
_VERSION_VALUE_RE = re.compile(
    r"^(?P<prefix>\s*version\s*:\s*)"
    r"(?P<quote>[\"']?)(?P<value>[^\"'#\s]+)(?P=quote)"
    r"(?P<suffix>\s*(?:#.*)?)$"
)


@dataclass(frozen=True)
class DockerImageVersionEntry:
    role: str
    service: str
    image: str
    version: str
    config_path: Path


@dataclass(frozen=True)
class DockerImageVersionUpdate:
    entry: DockerImageVersionEntry
    latest: str


def suppressed_services(config_path: Path) -> set[str]:
    """Return service names whose ``version:`` line is annotated with
    the unified ``# nocheck: docker-version`` marker.

    The file root of ``meta/services.yml`` IS the services map; there
    is no ``services.`` wrapper to walk into.
    """
    raw = read_text(str(config_path))
    lines = raw.splitlines()

    suppressed_lines: set[int] = {
        index
        for index, line in enumerate(lines)
        if re.search(r"^\s+version\s*:", line)
        and is_suppressed_at(lines, index + 1, "docker-version")
    }

    if not suppressed_lines:
        return set()

    root = yaml.compose(raw)
    if not isinstance(root, yaml.MappingNode):
        return set()

    names: set[str] = set()
    for service_key, service_value in root.value:
        if not isinstance(service_value, yaml.MappingNode):
            continue
        for field_key, _field_value in service_value.value:
            if (
                field_key.value == "version"
                and field_key.start_mark.line in suppressed_lines
            ):
                names.add(service_key.value)
    return names


def sourced_services(config_path: Path) -> set[str]:
    """Return service names whose ``version`` declares its own upstream.

    Args:
        config_path: a role's ``meta/services.yml``.
    """
    services = load_yaml(str(config_path)) or {}
    return {
        str(service)
        for service, config in services.items()
        if declares_source(config, "version")
    }


def collect_entries(repo_root: Path) -> list[DockerImageVersionEntry]:
    roles_root = repo_root / "roles"
    entries: list[DockerImageVersionEntry] = []

    for ref in iter_role_images(repo_root):
        if ref.derived:
            continue
        if ref.source_file != ROLE_FILE_META_SERVICES:
            continue
        if not is_semver(ref.version):
            continue
        if not is_maintained(roles_root, ref.role):
            continue

        config_path = roles_root / ref.role / ROLE_FILE_META_SERVICES
        if ref.service in suppressed_services(config_path):
            continue
        if ref.service in sourced_services(config_path):
            continue

        entries.append(
            DockerImageVersionEntry(
                role=ref.role,
                service=ref.service,
                image=_entry_image(ref),
                version=ref.version,
                config_path=config_path,
            )
        )

    return entries


def _entry_image(ref: ImageRef) -> str:
    return ref.name if ref.registry == "docker.io" else f"{ref.registry}/{ref.name}"


def collect_compose_entries(
    repo_root: Path, tracked: Iterable[str]
) -> list[DockerImageVersionEntry]:
    """Args:
        repo_root: repository root the tracked paths are relative to.
        tracked: repository-relative paths of the tracked files.

    Returns:
        One entry per semver-tagged service ``image`` literal of the
        :func:`compose_files`, scoped to the pseudo role ``RUNNER_ROLE``; its
        ``config_path`` is the compose file.
    """
    entries: list[DockerImageVersionEntry] = []
    for ref in iter_compose_images(repo_root, compose_files(repo_root, tracked)):
        compose_path = repo_root / ref.source_file
        if not is_semver(ref.version):
            continue
        if ref.service not in _compose_image_lines(read_text(str(compose_path))):
            continue
        if ref.service in suppressed_compose_services(compose_path):
            continue
        entries.append(
            DockerImageVersionEntry(
                role=ref.role,
                service=ref.service,
                image=_entry_image(ref),
                version=ref.version,
                config_path=compose_path,
            )
        )
    return entries


def _registry_cursor(version: str) -> str | None:
    """Pagination seed for the generic v2 tag scan.

    Returns ``"v"`` for v-prefixed pins so the scan skips ahead of
    commit-sha tags that sort before the release tags, ``None``
    otherwise (scan from the first page).
    """
    return "v" if version.startswith("v") else None


def find_outdated_updates(repo_root: Path) -> list[DockerImageVersionUpdate]:
    return outdated(collect_entries(repo_root))


def find_outdated_compose_updates(
    repo_root: Path, tracked: Iterable[str]
) -> list[DockerImageVersionUpdate]:
    return outdated(collect_compose_entries(repo_root, tracked))


def _follow_config(entry: DockerImageVersionEntry) -> object:
    if entry.role == RUNNER_ROLE:
        return None
    return (load_yaml(str(entry.config_path)) or {}).get(entry.service)


def outdated(entries: list[DockerImageVersionEntry]) -> list[DockerImageVersionUpdate]:
    """Args:
        entries: pins from :func:`collect_entries` or
            :func:`collect_compose_entries`.

    Returns:
        The bumps due for *entries*, release groups held together.
    """
    updates: list[DockerImageVersionUpdate] = []

    def _fetch(item: tuple[str, str]) -> tuple[str, list[str]]:
        image, version = item
        if is_dockerhub(image):
            return image, fetch_dockerhub_tags(image)
        if is_ghcr(image):
            return image, fetch_ghcr_tags(image)
        if is_mcr(image):
            return image, fetch_mcr_tags(image)
        return image, fetch_registry_tags(image, last=_registry_cursor(version))

    image_versions: dict[str, str] = {}
    for entry in entries:
        if is_supported_registry(entry.image):
            image_versions.setdefault(entry.image, entry.version)
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=resolve_max_fetch_workers()
    ) as pool:
        image_tags: dict[str, list[str]] = dict(
            pool.map(_fetch, image_versions.items())
        )

    for entry in entries:
        tags = followed_tags(
            entry.image,
            image_tags.get(entry.image, []),
            _follow_config(entry),
            entry.version,
        )
        if not tags:
            continue
        latest = latest_semver(
            tags,
            version_depth(entry.version),
            version_flavor(entry.version),
        )
        if latest and version_key(entry.version) < version_key(latest):
            updates.append(DockerImageVersionUpdate(entry=entry, latest=latest))

    return _held_to_release_groups(entries, updates, image_tags)


def _held_to_release_groups(
    entries: list[DockerImageVersionEntry],
    updates: list[DockerImageVersionUpdate],
    image_tags: dict[str, list[str]],
) -> list[DockerImageVersionUpdate]:
    """Hold every member of a release group to the newest tag all of them
    publish.

    Several images of one role (or one compose file) that currently sit on the
    same version are one product released together (the four Jitsi
    components, the six GitLab CNG images). Upstream does not push them
    atomically, so a run that lands in the window between the first and the
    last push would raise the ones already there and leave the rest behind,
    deploying a mixed set.

    Args:
        entries: every collected pin, so a member without a candidate of its
            own still holds its group.
        updates: the per-entry candidates, before grouping.
        image_tags: every tag fetched per image, keyed as in the caller.

    Returns:
        The updates, each group lowered to its common newest tag, and dropped
        entirely where a member has no candidate or the group shares no newer
        tag at all.
    """
    due = {update.entry: update for update in updates}
    groups: dict[tuple[str, Path, str], list[DockerImageVersionEntry]] = defaultdict(
        list
    )
    for entry in entries:
        groups[(entry.role, entry.config_path, entry.version)].append(entry)

    held: list[DockerImageVersionUpdate] = []
    for group in groups.values():
        if not all(entry in due for entry in group):
            continue
        if len(group) == 1:
            held.append(due[group[0]])
            continue
        shared = set.intersection(
            *(set(image_tags.get(entry.image, [])) for entry in group)
        )
        current = group[0].version
        common = latest_semver(
            sorted(shared), version_depth(current), version_flavor(current)
        )
        if not common or version_key(current) >= version_key(common):
            continue
        held.extend(
            DockerImageVersionUpdate(entry=entry, latest=common) for entry in group
        )

    return held


def update_config_versions(config_path: Path, service_versions: dict[str, str]) -> bool:
    """Rewrite each ``<service>.version:`` value in ``meta/services.yml``.

    The file root IS the services map (no ``services.`` wrapper), so the
    walker tracks one nesting level: top-level service keys and their
    immediate ``version:`` field. A service that moves to another version
    loses its ``image_tag`` CVE suppressions, which named the old tag.
    """
    lines = config_path.read_text(  # nocheck: cache-read — read-then-write of the same file; cached read would go stale
        encoding="utf-8"
    ).splitlines(keepends=True)
    moved: list[str] = []

    services_indent: int = 0
    current_service: str | None = None
    current_service_indent: int | None = None

    for index, line in enumerate(lines):
        match = _KEY_RE.match(line)
        if match is None:
            continue

        indent = len(match.group("indent"))
        key = match.group("key")

        if indent == services_indent:
            current_service = key
            current_service_indent = indent
            continue

        if current_service is None or current_service_indent is None:
            continue

        if indent <= current_service_indent:
            current_service = None
            current_service_indent = None
            continue

        if key != "version" or indent != current_service_indent + 2:
            continue

        replacement = service_versions.get(current_service)
        if replacement is None:
            continue

        version_match = _VERSION_VALUE_RE.match(line.rstrip("\n"))
        if version_match is None:
            continue

        quote = version_match.group("quote")
        current_value = version_match.group("value")
        if current_value == replacement:
            continue

        suffix = version_match.group("suffix")
        new_line = f"{version_match.group('prefix')}{quote}{replacement}{quote}{suffix}"
        if line.endswith("\n"):
            new_line += "\n"
        lines[index] = new_line
        moved.append(current_service)

    for service in moved:
        lines = drop_image_tag_entries(lines, service)
    if moved:
        config_path.write_text("".join(lines), encoding="utf-8")

    return bool(moved)


def apply_updates(updates: list[DockerImageVersionUpdate]) -> list[Path]:
    grouped: dict[tuple[Path, str], dict[str, str]] = {}
    for update in updates:
        entry = update.entry
        grouped.setdefault((entry.config_path, entry.role), {})[entry.service] = (
            update.latest
        )

    changed_paths: list[Path] = []
    for (config_path, role), service_versions in sorted(grouped.items()):
        rewrite = (
            update_compose_images if role == RUNNER_ROLE else update_config_versions
        )
        if rewrite(config_path, service_versions):
            changed_paths.append(config_path)
    return changed_paths
