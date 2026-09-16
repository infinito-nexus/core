"""Pinned Ansible collection versions in ``requirements/``.

Both requirement files name the same collections at the same versions: the
Galaxy file is the normal source, the git file the fallback used when
galaxy.ansible.com is unreachable. A bump that touches only one of them
would make the fallback install something the pin does not describe, so an
update is applied to both or to neither.

Upstream releases are resolved from the git file's own ``source:`` URL via
``git ls-remote --tags``, not from the Galaxy API, because the collections
are tagged in the repository the fallback already clones.

An entry whose ``version:`` is not a semver (a branch name, say) states an
intent this cannot second-guess and is skipped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from utils.cache.yaml import load_yaml_any
from utils.update.base import is_semver, version_key
from utils.update.repository import git_ls_remote_tags

GALAXY_REQUIREMENTS = Path("requirements/requirements.galaxy.yml")
GIT_REQUIREMENTS = Path("requirements/requirements.git.yml")


@dataclass(frozen=True)
class CollectionPin:
    """One collection pinned in both requirement files.

    Args:
        fqcn: fully qualified collection name, namespace and name.
        version: the version both files pin today.
        source: upstream git URL taken from the git requirements file.
    """

    fqcn: str
    version: str
    source: str


@dataclass(frozen=True)
class CollectionPinUpdate:
    pin: CollectionPin
    latest: str


def _entries(path: Path) -> list[dict]:
    declared = load_yaml_any(str(path), default_if_missing={}) or {}
    return [e for e in (declared.get("collections") or []) if isinstance(e, dict)]


def collect_pins(repo_root: Path) -> list[CollectionPin]:
    """Collections pinned to the same semver in both requirement files.

    Args:
        repo_root: repository root holding the ``requirements`` directory.
    """
    galaxy = {
        str(e.get("name")): str(e.get("version"))
        for e in _entries(repo_root / GALAXY_REQUIREMENTS)
        if e.get("name") and e.get("version")
    }
    pins: list[CollectionPin] = []
    for entry in _entries(repo_root / GIT_REQUIREMENTS):
        fqcn = str(entry.get("name", ""))
        version = str(entry.get("version", ""))
        source = str(entry.get("source", ""))
        if not (fqcn and source and is_semver(version)):
            continue
        if galaxy.get(fqcn) != version:
            continue
        pins.append(CollectionPin(fqcn=fqcn, version=version, source=source))
    return pins


def _highest_release(source: str, current: str) -> str | None:
    candidates = [
        tag
        for tag in git_ls_remote_tags(source)
        if is_semver(tag) and tag.lstrip("v").count(".") == current.count(".")
    ]
    if not candidates:
        return None
    newest = max(candidates, key=version_key)
    if version_key(newest) <= version_key(current):
        return None
    return newest.lstrip("v")


def find_outdated_updates(repo_root: Path) -> list[CollectionPinUpdate]:
    """Pins whose upstream carries a higher release tag.

    Args:
        repo_root: repository root holding the ``requirements`` directory.
    """
    updates: list[CollectionPinUpdate] = []
    for pin in collect_pins(repo_root):
        latest = _highest_release(pin.source, pin.version)
        if latest:
            updates.append(CollectionPinUpdate(pin=pin, latest=latest))
    return updates


def _rewrite(path: Path, fqcn: str, old: str, new: str) -> bool:
    text = path.read_text(
        encoding="utf-8"
    )  # nocheck: cache-read -- rewritten below, a cached copy would go stale mid-run
    pattern = re.compile(
        rf"(name:\s*{re.escape(fqcn)}\b(?:\n(?!\s*-\s).*)*?\n\s*version:\s*){re.escape(old)}\b"
    )
    replaced, count = pattern.subn(rf"\g<1>{new}", text)
    if not count:
        return False
    path.write_text(replaced, encoding="utf-8")
    return True


def apply_updates(repo_root: Path, updates: list[CollectionPinUpdate]) -> list[Path]:
    """Write every update into both requirement files.

    Args:
        repo_root: repository root holding the ``requirements`` directory.
        updates: the bumps to apply, as returned by :func:`find_outdated_updates`.
    """
    changed: set[Path] = set()
    for update in updates:
        for relative in (GALAXY_REQUIREMENTS, GIT_REQUIREMENTS):
            path = repo_root / relative
            if _rewrite(path, update.pin.fqcn, update.pin.version, update.latest):
                changed.add(path)
    return sorted(changed)
