from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.cache.yaml import load_yaml_any
from utils.digests import COMMIT
from utils.roles.custom import MANIFEST_COMMIT_KEY, MANIFEST_FILE, RELEASE_TAG
from utils.update.base import version_key
from utils.update.repository import git_ls_remote_tag_commits

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class CustomRolePin:
    """
    Args:
        group: the custom role the manifest pins.
        url: its repository.
        version: the pinned tag.
        commit: the commit the pinned tag resolves to.
    """

    group: str
    url: str
    version: str
    commit: str


@dataclass(frozen=True)
class CustomRolePinUpdate:
    """
    Args:
        pin: the pin as the manifest holds it.
        version: the newest release tag of the repository.
        commit: the commit that tag resolves to.
    """

    pin: CustomRolePin
    version: str
    commit: str


def collect_pins(repo_root: Path) -> list[CustomRolePin]:
    """Args:
        repo_root: repository root holding the manifest.

    Returns:
        Every manifest entry whose ``version`` is a release tag ``vX.Y.Z``
        or ``X.Y.Z`` and whose ``commit`` is a full commit SHA.
    """
    data = load_yaml_any(str(repo_root / MANIFEST_FILE), default_if_missing={})
    entries = data.items() if isinstance(data, dict) else ()
    pins: list[CustomRolePin] = []
    for group, entry in sorted(entries, key=lambda item: str(item[0])):
        fields = entry if isinstance(entry, dict) else {}
        url, version, commit = (
            fields.get(key) for key in ("url", "version", MANIFEST_COMMIT_KEY)
        )
        if (
            isinstance(url, str)
            and isinstance(version, str)
            and RELEASE_TAG.fullmatch(version)
            and isinstance(commit, str)
            and COMMIT.fullmatch(commit)
        ):
            pins.append(CustomRolePin(str(group), url, version, commit))
    return pins


def _newest_release(pin: CustomRolePin) -> CustomRolePinUpdate | None:
    commits = git_ls_remote_tag_commits(pin.url)
    newest = max(filter(RELEASE_TAG.fullmatch, commits), key=version_key, default=None)
    if newest is None or version_key(newest) <= version_key(pin.version):
        return None
    commit = commits[newest]
    if not COMMIT.fullmatch(commit):
        return None
    return CustomRolePinUpdate(pin=pin, version=newest, commit=commit)


def find_outdated_updates(repo_root: Path) -> list[CustomRolePinUpdate]:
    """Args:
        repo_root: repository root holding the manifest.

    Returns:
        One update per pin whose repository carries a newer release tag
        ``vX.Y.Z`` or ``X.Y.Z``, with the commit the tag peels to; a moving
        tag such as ``latest`` and a prerelease are never picked.
    """
    return [
        update
        for update in map(_newest_release, collect_pins(repo_root))
        if update is not None
    ]


def _rewrite(text: str, update: CustomRolePinUpdate) -> str:
    block = re.compile(
        rf"(?m)^{re.escape(update.pin.group)}:[ \t]*\n(?:[ \t]+.*(?:\n|\Z)|[ \t]*\n)*"
    )
    match = block.search(text)
    if match is None:
        return text
    body = match.group(0)
    for key, old, new in (
        ("version", update.pin.version, update.version),
        (MANIFEST_COMMIT_KEY, update.pin.commit, update.commit),
    ):
        body = re.sub(
            rf"(?m)^([ \t]+{key}:[ \t]*)([\"']?){re.escape(old)}\2([ \t]*(?:#.*)?)$",
            lambda found, value=new: f"{found[1]}{found[2]}{value}{found[2]}{found[3]}",
            body,
        )
    return f"{text[: match.start()]}{body}{text[match.end() :]}"


def apply_updates(repo_root: Path, updates: list[CustomRolePinUpdate]) -> list[Path]:
    """Args:
        repo_root: repository root holding the manifest.
        updates: the bumps :func:`find_outdated_updates` returned.

    Returns:
        The manifest when it changed, else nothing.
    """
    path = repo_root / MANIFEST_FILE
    if not updates:
        return []
    text = path.read_text(  # nocheck: cache-read -- rewritten below, a cached copy would go stale
        encoding="utf-8"
    )
    rewritten = text
    for update in updates:
        rewritten = _rewrite(rewritten, update)
    if rewritten == text:
        return []
    path.write_text(rewritten, encoding="utf-8")
    return [path]
