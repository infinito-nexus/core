from __future__ import annotations

import re
from typing import Any

from ansible.errors import AnsibleFilterError

LAST_MIGRATION_VERSIONS: dict[str, int] = {
    "6.0.0": 800,
    "6.0.1": 800,
    "6.0.2": 800,
    "6.0.3": 800,
    "6.0.4": 800,
    "6.1.0": 835,
    "6.2.0": 860,
    "6.2.1": 860,
    "6.3.0": 865,
    "6.3.1": 865,
    "6.3.2": 865,
    "6.3.3": 865,
    "7.0.0": 865,
    "7.0.1": 865,
    "7.1.0": 875,
    "7.1.1": 875,
    "7.2.0": 895,
    "7.2.1": 895,
    "7.2.2": 895,
    "7.2.3": 895,
    "7.3.0": 925,
    "8.0.0": 970,
    "8.0.1": 970,
    "8.0.2": 970,
    "8.1.0": 1000,
    "8.1.1": 1000,
    "8.1.2": 1000,
    "8.1.3": 1000,
    "8.1.4": 1000,
    "8.1.5": 1000,
    "8.1.6": 1000,
    "8.1.7": 1000,
    "8.1.8": 1001,
    "8.2.0": 1040,
    "8.2.1": 1040,
    "8.2.2": 1040,
    "8.2.3": 1040,
    "8.2.4": 1040,
    "8.3.0": 1125,
    "8.3.1": 1130,
}

_RELEASE_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-[0-9A-Za-z.-]+)?$")
_SCRIPT_RE = re.compile(r"^peertube-(\d+)\.(\d+)(?:\.(\d+))?\.js$")


def _key(release: str) -> tuple[int, ...]:
    return tuple(int(part) for part in release.split("."))


def peertube_release(version: Any) -> str:
    """Normalise an image tag or a recorded release.

    Args:
        version: ``v8.3.1``, ``v7.3.0-bookworm`` or ``8.3.1``.

    Returns:
        The release as ``X.Y.Z``.
    """
    match = _RELEASE_RE.match(str(version).strip())
    if match is None:
        raise AnsibleFilterError(
            f"peertube_release: {version!r} names no PeerTube release; "
            "pin services.peertube.version to an explicit vX.Y.Z tag"
        )
    return ".".join(match.groups())


def peertube_migration_version(release: Any) -> int:
    """Look up the schema version a release migrates its database to.

    Args:
        release: a release in any form ``peertube_release`` accepts.

    Returns:
        The ``LAST_MIGRATION_VERSION`` of that release.
    """
    normalised = peertube_release(release)
    if normalised not in LAST_MIGRATION_VERSIONS:
        raise AnsibleFilterError(
            f"peertube_migration_version: release {normalised} is missing from "
            "LAST_MIGRATION_VERSIONS in roles/web-app-peertube/filter_plugins/"
            "peertube_upgrade.py; add its LAST_MIGRATION_VERSION from "
            "server/core/initializers/constants.ts"
        )
    return LAST_MIGRATION_VERSIONS[normalised]


def _release_for_migration(migration: int, ceiling: str) -> str:
    candidates = [
        release
        for release, last in LAST_MIGRATION_VERSIONS.items()
        if last <= migration and _key(release) <= _key(ceiling)
    ]
    if not candidates:
        oldest = min(LAST_MIGRATION_VERSIONS, key=_key)
        raise AnsibleFilterError(
            f"PeerTube data at migration {migration} predates release {oldest}, "
            "the oldest release the role can place; upgrade it by hand first"
        )
    return max(candidates, key=_key)


def peertube_upgrade_plan(pinned: Any, marker: Any, migration: Any) -> dict[str, Any]:
    """Decide what a deploy of ``pinned`` has to do to the existing data.

    Args:
        pinned: the image version this deploy rolls out.
        marker: the release recorded on this host before the pinned image
            started, ``""`` when none was recorded.
        migration: ``application.migrationVersion`` read before the pinned
            image started, ``""`` when the database holds no PeerTube data,
            ``None`` when the database could not be read.

    Returns:
        ``pinned``: the pinned release.
        ``data``: the oldest release the existing data may still be on,
        ``""`` when there is no data.
        ``upgrade``: whether ``data`` is older than ``pinned``.
        ``replace_assets``: whether the image-seeded client assets may come
        from another release than ``pinned``.
    """
    pinned_release = peertube_release(pinned)
    pinned_migration = peertube_migration_version(pinned_release)
    marker_release = peertube_release(marker) if str(marker).strip() else ""

    if marker_release and _key(marker_release) > _key(pinned_release):
        raise AnsibleFilterError(
            f"PeerTube data was deployed with release {marker_release}, newer "
            f"than the pinned release {pinned_release}; refusing to downgrade"
        )

    if migration is None:
        data = marker_release
    elif not str(migration).strip():
        data = ""
    else:
        data_migration = int(migration)
        if data_migration > pinned_migration:
            raise AnsibleFilterError(
                f"PeerTube data is at migration {data_migration}, newer than "
                f"migration {pinned_migration} of the pinned release "
                f"{pinned_release}; refusing to downgrade"
            )
        known = [_release_for_migration(data_migration, pinned_release)]
        if marker_release:
            known.append(marker_release)
        data = min(known, key=_key)

    existing = bool(marker_release or data)
    stale = marker_release != pinned_release or data not in ("", pinned_release)
    return {
        "pinned": pinned_release,
        "data": data,
        "upgrade": bool(data) and _key(data) < _key(pinned_release),
        "replace_assets": existing and stale,
    }


def peertube_migration_scripts(filenames: Any, data: Any, pinned: Any) -> list[str]:
    """Pick the manual migration scripts an upgrade has to run.

    Args:
        filenames: the entries of ``dist/scripts/migrations`` in the pinned
            image.
        data: the release the existing data is on.
        pinned: the release this deploy rolls out.

    Returns:
        The ``peertube-X.Y.js`` names above ``data`` up to ``pinned``,
        oldest first.
    """
    lower = _key(peertube_release(data))
    upper = _key(peertube_release(pinned))
    selected: list[tuple[tuple[int, ...], str]] = []
    for name in filenames:
        match = _SCRIPT_RE.match(str(name).strip())
        if match is None:
            continue
        release = tuple(int(part or 0) for part in match.groups())
        if lower < release <= upper:
            selected.append((release, str(name).strip()))
    return [name for _, name in sorted(selected)]


class FilterModule:
    def filters(self):
        return {
            "peertube_release": peertube_release,
            "peertube_migration_version": peertube_migration_version,
            "peertube_upgrade_plan": peertube_upgrade_plan,
            "peertube_migration_scripts": peertube_migration_scripts,
        }
