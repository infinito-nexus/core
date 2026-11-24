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
    frozen: list[DockerImageVersionEntry],
    updates: list[DockerImageVersionUpdate],
    image_tags: dict[str, list[str]],
    repo_root: Path,
) -> list[DockerImageVersionUpdate]:
    """
    Args:
        entries: every watched pin.
        frozen: the held pins ``# nocheck: docker-version`` keeps out of
            *entries*; they propose nothing but still hold their group.
        updates: the per-entry candidates, before grouping.
        image_tags: every tag fetched per image.
        repo_root: the repository the pins' files sit in.

    Returns:
        The candidates no hold blocks, each release group lowered to its
        common newest tag; every blocked candidate is reported as a warning.
    """
    free, held = _split_holds([*entries, *frozen], updates)
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
    return _held_to_release_groups(entries, free, image_tags)


def _release_group(entry: DockerImageVersionEntry) -> tuple[str, Path, str]:
    """
    Args:
        entry: a pin.

    Returns:
        The key every pin of one role or compose file on one version shares.
    """
    return (entry.role, entry.config_path, entry.version)


def _split_holds(
    holders: list[DockerImageVersionEntry], updates: list[DockerImageVersionUpdate]
) -> tuple[list[DockerImageVersionUpdate], list[DockerImageVersionHold]]:
    """
    Args:
        holders: every pin whose ``hold`` may block its release group.
        updates: the per-entry candidates, before grouping.

    Returns:
        The candidates outside every release group with a held member, and
        one hold per candidate inside one, naming that member.
    """
    held_groups: dict[tuple[str, Path, str], DockerImageVersionEntry] = {}
    for entry in holders:
        if entry.hold:
            held_groups.setdefault(_release_group(entry), entry)
    free: list[DockerImageVersionUpdate] = []
    held: list[DockerImageVersionHold] = []
    for update in updates:
        holder = held_groups.get(_release_group(update.entry))
        if holder is None:
            free.append(update)
        else:
            held.append(DockerImageVersionHold(update=update, holder=holder))
    return free, held


def _held_to_release_groups(
    entries: list[DockerImageVersionEntry],
    updates: list[DockerImageVersionUpdate],
    image_tags: dict[str, list[str]],
) -> list[DockerImageVersionUpdate]:
    """
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
        groups[_release_group(entry)].append(entry)

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
        held.extend(replace(due[entry], latest=common) for entry in group)

    return held
