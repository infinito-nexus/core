from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from utils.annotations.message import warning
from utils.update.base import latest_semver, version_depth, version_flavor, version_key

if TYPE_CHECKING:
    from pathlib import Path

    from utils.update.docker import DockerImageVersionEntry, DockerImageVersionUpdate


@dataclass(frozen=True)
class DockerImageVersionHold:
    update: DockerImageVersionUpdate
    holder: DockerImageVersionEntry


def releasable_updates(
    entries: list[DockerImageVersionEntry],
    updates: list[DockerImageVersionUpdate],
    image_tags: dict[str, list[str]],
    repo_root: Path,
) -> list[DockerImageVersionUpdate]:
    """
    Args:
        entries: every watched pin.
        updates: the per-entry candidates, before grouping.
        image_tags: every tag fetched per image.
        repo_root: the repository whose ``roles/`` hold the pins.

    Returns:
        The candidates no hold blocks, each release group lowered to its
        common newest tag; every blocked candidate is reported as a warning.
    """
    free, held = _split_holds(entries, updates)
    for hold in held:
        update = hold.update
        warning(
            f"[hold] {update.entry.role}/{update.entry.service}: "
            f"{update.entry.image} stays at {update.entry.version}, "
            f"{update.latest} is available; held by {hold.holder.service}: "
            f"{hold.holder.hold}",
            title="Held Docker image",
            file=str(update.entry.config_path.relative_to(repo_root)),
        )
    return _held_to_release_groups(free, image_tags)


def _split_holds(
    entries: list[DockerImageVersionEntry], updates: list[DockerImageVersionUpdate]
) -> tuple[list[DockerImageVersionUpdate], list[DockerImageVersionHold]]:
    """
    Args:
        entries: every watched pin.
        updates: the per-entry candidates, before grouping.

    Returns:
        The candidates outside every release group with a held member, and
        one hold per candidate inside one, naming that member.
    """
    holders: dict[tuple[str, str], DockerImageVersionEntry] = {}
    for entry in entries:
        if entry.hold:
            holders.setdefault((entry.role, entry.version), entry)
    free: list[DockerImageVersionUpdate] = []
    held: list[DockerImageVersionHold] = []
    for update in updates:
        holder = holders.get((update.entry.role, update.entry.version))
        if holder is None:
            free.append(update)
        else:
            held.append(DockerImageVersionHold(update=update, holder=holder))
    return free, held


def _held_to_release_groups(
    updates: list[DockerImageVersionUpdate], image_tags: dict[str, list[str]]
) -> list[DockerImageVersionUpdate]:
    """
    Args:
        updates: the per-entry candidates, before grouping.
        image_tags: every tag fetched per image, keyed as in the caller.

    Returns:
        The updates, each group lowered to its common newest tag, and dropped
        entirely where the group shares no newer tag at all.
    """
    groups: dict[tuple[str, str], list[DockerImageVersionUpdate]] = defaultdict(list)
    for update in updates:
        groups[(update.entry.role, update.entry.version)].append(update)

    held: list[DockerImageVersionUpdate] = []
    for group in groups.values():
        if len(group) == 1:
            held.extend(group)
            continue
        shared = set.intersection(
            *(set(image_tags.get(update.entry.image, [])) for update in group)
        )
        current = group[0].entry.version
        common = latest_semver(
            sorted(shared), version_depth(current), version_flavor(current)
        )
        if not common or version_key(current) >= version_key(common):
            continue
        held.extend(replace(update, latest=common) for update in group)

    return held
