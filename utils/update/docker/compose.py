"""Compose-file side of :mod:`utils.update.docker`: which tracked YAML files
declare compose images, where their ``image:`` tags sit, and the rewrite of
those tags."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import yaml

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.meta.role.names import ROLES_DIR

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

_IMAGE_VALUE_RE = re.compile(
    r"^(?P<prefix>\s*image\s*:\s*)"
    r"(?P<quote>[\"']?)(?P<name>[^\"'#\s]+):(?P<tag>[^\"'#\s:/@]+)(?P=quote)"
    r"(?P<suffix>\s*(?:#.*)?)$"
)
COMPOSE_SUFFIXES = (".yml", ".yaml")
DEPENDABOT_COMPOSE_FILES = (
    "compose.yml",
    "compose.yaml",
    "docker-compose.yml",
    "docker-compose.yaml",
)
TEST_TREE = "tests"


def declares_compose_images(document: object) -> bool:
    """Args:
        document: a parsed YAML document.

    Returns:
        Whether its top level holds a ``services`` mapping in which at least
        one service carries an ``image`` string.
    """
    services = document.get("services") if isinstance(document, dict) else None
    return isinstance(services, dict) and any(
        isinstance(spec, dict) and isinstance(spec.get("image"), str)
        for spec in services.values()
    )


def _owned_candidate(rel: str) -> bool:
    path = PurePosixPath(rel)
    return (
        rel.endswith(COMPOSE_SUFFIXES)
        and path.name not in DEPENDABOT_COMPOSE_FILES
        and path.parts[0] not in (TEST_TREE, ROLES_DIR)
    )


def compose_files(repo_root: Path, tracked: Iterable[str]) -> list[str]:
    """Args:
        repo_root: repository root the tracked paths are relative to.
        tracked: repository-relative POSIX paths of the tracked files, as
            :func:`utils.cache.files.repository_files` lists them.

    Returns:
        The tracked YAML files :func:`declares_compose_images` accepts,
        sorted. Left out are Jinja templates, YAML that does not parse as one
        document, the test tree ``TEST_TREE``, the role tree ``ROLES_DIR``,
        whose images ``meta/services.yml`` pins for
        :func:`utils.update.docker.collect_entries`, and the files
        Dependabot's ``docker-compose`` ecosystem bumps
        (``DEPENDABOT_COMPOSE_FILES``).
    """
    owned: list[str] = []
    for rel in tracked:
        if not _owned_candidate(rel):
            continue
        path = repo_root / rel
        try:
            if "services" not in read_text(str(path)):
                continue
            document = load_yaml_any(str(path))
        except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError):
            continue
        if declares_compose_images(document):
            owned.append(rel)
    return sorted(owned)


def _defined_in_place(key: yaml.Node, value: yaml.Node) -> bool:
    """Args:
        key: a mapping key node.
        value: the node composed for that key.

    Returns:
        Whether *value* is written after *key* rather than being an alias,
        which composes to the anchored node with that node's source marks.
    """
    return value.start_mark.index >= key.end_mark.index


def _compose_image_lines(raw: str) -> dict[str, int]:
    """Args:
        raw: text of a compose file.

    Returns:
        Each compose service mapped to the 0-indexed line of its ``image``
        key, for the keys whose tagged value sits on that line in the one
        form ``_IMAGE_VALUE_RE`` rewrites. A service that aliases a mapping
        anchored elsewhere is left out: its line belongs to the anchor, and
        rewriting it would move every service merging that anchor as well.
    """
    text_lines = raw.splitlines()
    root = yaml.compose(raw)
    services = next(
        (
            value
            for key, value in (root.value if isinstance(root, yaml.MappingNode) else [])
            if key.value == "services" and isinstance(value, yaml.MappingNode)
        ),
        None,
    )
    lines: dict[str, int] = {}
    for service, spec in services.value if services else []:
        if not isinstance(spec, yaml.MappingNode) or not _defined_in_place(
            service, spec
        ):
            continue
        for field, value in spec.value:
            line = field.start_mark.line
            if (
                field.value == "image"
                and value.start_mark.line == line
                and _IMAGE_VALUE_RE.match(text_lines[line])
            ):
                lines[service.value] = line
    return lines


def suppressed_compose_services(compose_path: Path) -> set[str]:
    """Args:
        compose_path: a compose file of the repository.

    Returns:
        The services whose ``image:`` carries ``# nocheck: docker-version``.
    """
    raw = read_text(str(compose_path))
    lines = raw.splitlines()
    return {
        service
        for service, line in _compose_image_lines(raw).items()
        if is_suppressed_at(lines, line + 1, "docker-version")
    }


def update_compose_images(compose_path: Path, service_versions: dict[str, str]) -> bool:
    """Args:
        compose_path: a compose file of the repository.
        service_versions: service name to the tag its image moves to.

    Returns:
        Whether the file changed; every line but the rewritten tags stays as
        it was.
    """
    raw = compose_path.read_text(  # nocheck: cache-read -- read-then-write of the same file; a cached read would go stale
        encoding="utf-8"
    )
    lines = raw.splitlines(keepends=True)
    changed = False
    for service, line in _compose_image_lines(raw).items():
        latest = service_versions.get(service)
        body = lines[line].rstrip("\n")
        match = _IMAGE_VALUE_RE.match(body)
        if latest is None or match is None or match["tag"] == latest:
            continue
        quote = match["quote"]
        lines[line] = (
            f"{match['prefix']}{quote}{match['name']}:{latest}{quote}"
            f"{match['suffix']}{lines[line][len(body) :]}"
        )
        changed = True
    if changed:
        compose_path.write_text("".join(lines), encoding="utf-8")
    return changed
