from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlencode

import yaml

from utils.docker.image.discovery import iter_role_images
from utils.docker.image.ref import (
    DOCKER_HUB_REGISTRIES,
    GHCR_REGISTRY,
    split_registry_and_name,
)

_SEMVER_CORE = r"v?\d+(?:\.\d+){0,3}"
# Tags that extend a semver with a `-<flavor>` suffix, e.g. the Docker
# Official image tag `5.4.5-php8.3-apache`. The flavor is treated as an
# opaque discriminator: tags are only considered upgrade candidates for
# each other when their flavor strings match.
_VERSIONED_TAG_RE = re.compile(rf"^(?P<semver>{_SEMVER_CORE})(?P<flavor>-\S+)?$")
_NOCHECK_TAG = "# nocheck: docker-version"
_KEY_RE = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z0-9_-]+):(?P<rest>.*)$")
_VERSION_VALUE_RE = re.compile(
    r"^(?P<prefix>\s*version\s*:\s*)(?P<quote>[\"']?)(?P<value>[^\"'#\s]+)(?P=quote)(?P<suffix>\s*(?:#.*)?)$"
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


def _parse_versioned_tag(tag: str) -> tuple[str, str] | None:
    match = _VERSIONED_TAG_RE.match(str(tag).strip())
    if match is None:
        return None
    return match.group("semver"), match.group("flavor") or ""


def is_semver(value: str) -> bool:
    return _parse_versioned_tag(value) is not None


def version_key(tag: str) -> tuple[int, ...]:
    parsed = _parse_versioned_tag(tag)
    if parsed is None:
        return (0,) * 4
    semver, _flavor = parsed
    parts = tuple(int(part) for part in semver.lstrip("v").split("."))
    return parts + (0,) * (4 - len(parts))


def version_depth(tag: str) -> int:
    parsed = _parse_versioned_tag(tag)
    if parsed is None:
        return 0
    semver, _flavor = parsed
    return len(semver.lstrip("v").split("."))


def version_flavor(tag: str) -> str:
    """Return the `-<flavor>` suffix of a versioned tag, or "" when none.

    Only tags that share the same flavor are considered upgrade candidates
    for one another, so that e.g. `5.4.5-php8.3-apache` is never
    auto-bumped to `5.4.6-php8.4-apache` (different runtime flavor) or to
    `5.4.6-php8.3-fpm` (different webserver flavor).
    """
    parsed = _parse_versioned_tag(tag)
    return parsed[1] if parsed else ""


def latest_semver(tags: list[str], depth: int, flavor: str = "") -> str | None:
    candidates = [
        tag
        for tag in tags
        if is_semver(tag)
        and version_depth(tag) == depth
        and version_flavor(tag) == flavor
    ]
    return max(candidates, key=version_key, default=None)


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
        req = urllib.request.Request(
            url, headers={"User-Agent": "infinito-nexus-version-updater"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
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
        req = urllib.request.Request(
            token_url, headers={"User-Agent": "infinito-nexus-version-updater"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            token_body = json.loads(resp.read().decode())
        token = token_body.get("token") or token_body.get("access_token")
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return []

    if not token:
        return []

    tags_url = f"https://{GHCR_REGISTRY}/v2/{quote(name, safe='/')}/tags/list"
    req = urllib.request.Request(
        tags_url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "infinito-nexus-version-updater",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return []

    return body.get("tags") or []


def suppressed_services(config_path: Path) -> set[str]:
    """Return service names whose `version:` line carries the suppress tag.

    Post req-008 the file root of `meta/services.yml` IS the services map —
    there is no `services.` wrapper to walk into.
    """
    raw = config_path.read_text(encoding="utf-8")
    lines = raw.splitlines()

    suppressed_lines: set[int] = set()
    for index, line in enumerate(lines):
        if not re.search(r"^\s+version\s*:", line):
            continue
        for prev_index in range(index - 1, -1, -1):
            prev = lines[prev_index].strip()
            if prev == _NOCHECK_TAG:
                suppressed_lines.add(index)
                break
            if prev and not prev.startswith("#"):
                break

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
        if not ref.role.startswith("web-"):
            continue
        if ref.source_file != "meta/services.yml":
            continue
        if not is_semver(ref.version):
            continue

        config_path = roles_root / ref.role / "meta" / "services.yml"
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


def find_outdated_updates(repo_root: Path) -> list[DockerImageVersionUpdate]:
    entries = collect_entries(repo_root)
    image_tags: dict[str, list[str]] = {}
    updates: list[DockerImageVersionUpdate] = []

    for entry in entries:
        if entry.image in image_tags:
            continue
        if is_dockerhub(entry.image):
            image_tags[entry.image] = fetch_dockerhub_tags(entry.image)
        elif is_ghcr(entry.image):
            image_tags[entry.image] = fetch_ghcr_tags(entry.image)

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
    """Rewrite each ``<service>.version:`` value in `meta/services.yml`.

    The post-req-008 file root IS the services map (no `services.`
    wrapper), so the walker tracks one nesting level: top-level service keys
    and their immediate ``version:`` field.
    """
    lines = config_path.read_text(encoding="utf-8").splitlines(keepends=True)
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
