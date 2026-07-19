"""Detect and rewrite outdated Docker image `version:` tags in
`roles/*/meta/services.yml`.

Counterpart to :mod:`utils.update.repository` (which handles git refs).
Both share the semver primitives in :mod:`utils.update.base`; this
module owns the Docker-Hub / GHCR registry lookups and the YAML
walker that rewrites the matching ``version:`` line.

Suppress a check by placing ``# nocheck: docker-version`` on the line
directly above the ``version:`` key.
"""

from __future__ import annotations

import concurrent.futures
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import quote, urlencode

import yaml

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text
from utils.docker.image.discovery import iter_role_images
from utils.docker.image.ref import (
    DOCKER_HUB_REGISTRIES,
    GHCR_REGISTRY,
    MCR_REGISTRY,
    split_registry_and_name,
)
from utils.docker.registry import fetch_registry_tags
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.update.base import (
    is_semver,
    latest_semver,
    resolve_max_fetch_workers,
    version_depth,
    version_flavor,
    version_key,
)

if TYPE_CHECKING:
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


def is_dockerhub(image: str) -> bool:
    parsed = split_registry_and_name(image)
    if parsed is None:
        return False
    registry, _name = parsed
    return registry is None or registry in DOCKER_HUB_REGISTRIES


def dockerhub_repo(image: str) -> str:
    parsed = split_registry_and_name(image)
    if parsed is None:
        raise ValueError(f"Invalid Docker image reference: {image!r}")
    registry, name = parsed
    if registry is not None and registry not in DOCKER_HUB_REGISTRIES:
        raise ValueError(f"Image is not a Docker Hub reference: {image!r}")
    return name if "/" in name else f"library/{name}"


def fetch_dockerhub_tags(image: str, max_pages: int = 5) -> list[str]:
    repo = dockerhub_repo(image)
    tags: list[str] = []
    for page in range(1, max_pages + 1):
        url = (
            f"https://hub.docker.com/v2/repositories/{repo}/tags/"
            f"?page_size=100&page={page}"
        )
        req = urllib.request.Request(  # noqa: S310
            url, headers={"User-Agent": "infinito-nexus-version-updater"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
                if resp.status == 429:
                    time.sleep(2)
                    continue
                body = json.loads(resp.read().decode())
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            break
        tags.extend(item["name"] for item in body.get("results", []))
        if not body.get("next"):
            break
    return tags


def is_ghcr(image: str) -> bool:
    parsed = split_registry_and_name(image)
    return parsed is not None and parsed[0] == GHCR_REGISTRY


def ghcr_repo(image: str) -> str:
    parsed = split_registry_and_name(image)
    if parsed is None or parsed[0] != GHCR_REGISTRY:
        raise ValueError(f"Image is not a GHCR reference: {image!r}")
    return parsed[1]


def fetch_ghcr_tags(image: str) -> list[str]:
    name = ghcr_repo(image)
    token_query = urlencode(
        {"scope": f"repository:{name}:pull", "service": GHCR_REGISTRY}
    )
    token_url = f"https://{GHCR_REGISTRY}/token?{token_query}"
    try:
        req = urllib.request.Request(  # noqa: S310
            token_url, headers={"User-Agent": "infinito-nexus-version-updater"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            token_body = json.loads(resp.read().decode())
        token = token_body.get("token") or token_body.get("access_token")
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return []

    if not token:
        return []

    tags_url = f"https://{GHCR_REGISTRY}/v2/{quote(name, safe='/')}/tags/list"
    req = urllib.request.Request(  # noqa: S310
        tags_url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "infinito-nexus-version-updater",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            body = json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return []

    return body.get("tags") or []


def is_mcr(image: str) -> bool:
    parsed = split_registry_and_name(image)
    return parsed is not None and parsed[0] == MCR_REGISTRY


def is_supported_registry(image: str) -> bool:
    """Whether *image* resolves to a registry the generic v2 client can query."""
    return split_registry_and_name(image) is not None


def mcr_repo(image: str) -> str:
    parsed = split_registry_and_name(image)
    if parsed is None or parsed[0] != MCR_REGISTRY:
        raise ValueError(f"Image is not an MCR reference: {image!r}")
    return parsed[1]


_LINK_NEXT_RE = re.compile(r'<([^>]+)>\s*;\s*rel="next"', re.IGNORECASE)


def fetch_mcr_tags(image: str, max_pages: int = 10) -> list[str]:
    name = mcr_repo(image)
    base = f"https://{MCR_REGISTRY}"
    url = f"{base}/v2/{quote(name, safe='/')}/tags/list?n=100"
    tags: list[str] = []
    for _ in range(max_pages):
        req = urllib.request.Request(  # noqa: S310
            url, headers={"User-Agent": "infinito-nexus-version-updater"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
                body = json.loads(resp.read().decode())
                link_header = resp.headers.get("Link", "")
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            break
        tags.extend(body.get("tags") or [])
        match = _LINK_NEXT_RE.search(link_header)
        if not match:
            break
        next_link = match.group(1)
        url = next_link if next_link.startswith("http") else f"{base}{next_link}"
    return tags


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


def collect_entries(repo_root: Path) -> list[DockerImageVersionEntry]:
    roles_root = repo_root / "roles"
    entries: list[DockerImageVersionEntry] = []

    for ref in iter_role_images(repo_root):
        if ref.source_file != ROLE_FILE_META_SERVICES:
            continue
        if not is_semver(ref.version):
            continue

        config_path = roles_root / ref.role / ROLE_FILE_META_SERVICES
        if ref.service in suppressed_services(config_path):
            continue

        if ref.registry == "docker.io":
            image = ref.name
        else:
            image = f"{ref.registry}/{ref.name}"

        entries.append(
            DockerImageVersionEntry(
                role=ref.role,
                service=ref.service,
                image=image,
                version=ref.version,
                config_path=config_path,
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
    entries = collect_entries(repo_root)
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
        tags = image_tags.get(entry.image, [])
        if not tags:
            continue
        latest = latest_semver(
            tags,
            version_depth(entry.version),
            version_flavor(entry.version),
        )
        if latest and version_key(entry.version) < version_key(latest):
            updates.append(DockerImageVersionUpdate(entry=entry, latest=latest))

    return updates


def update_config_versions(config_path: Path, service_versions: dict[str, str]) -> bool:
    """Rewrite each ``<service>.version:`` value in ``meta/services.yml``.

    The file root IS the services map (no ``services.`` wrapper), so the
    walker tracks one nesting level: top-level service keys and their
    immediate ``version:`` field.
    """
    lines = config_path.read_text(  # nocheck: cache-read — read-then-write of the same file; cached read would go stale
        encoding="utf-8"
    ).splitlines(keepends=True)
    changed = False

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
        changed = True

    if changed:
        config_path.write_text("".join(lines), encoding="utf-8")

    return changed


def apply_updates(updates: list[DockerImageVersionUpdate]) -> list[Path]:
    grouped: dict[Path, dict[str, str]] = {}
    for update in updates:
        grouped.setdefault(update.entry.config_path, {})[update.entry.service] = (
            update.latest
        )

    changed_paths: list[Path] = []
    for config_path, service_versions in sorted(grouped.items()):
        if update_config_versions(config_path, service_versions):
            changed_paths.append(config_path)
    return changed_paths
