from __future__ import annotations

import json
import os
import stat
from typing import TYPE_CHECKING

from utils.design.gallery import gaps, manifest

if TYPE_CHECKING:
    from pathlib import Path

PROPOSAL_FILE = "proposal.json"


def _owned(path: Path, kind: int) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_IFMT(info.st_mode) == kind and info.st_uid == os.getuid()


def file_proposal(gallery: Path, findings: list[str]) -> Path:
    """Write the design proposal of one app next to its screenshots.

    Args:
        gallery: the app's gallery directory, filled by ``make design-gallery``.
        findings: one line per proposed design change.

    Returns:
        The written proposal file.

    Raises:
        ValueError: ``findings`` holds no text or a non-text entry, or the
            gallery or its root is missing, a symlink, or another user's.
    """
    if not findings or not all(isinstance(f, str) and f.strip() for f in findings):
        raise ValueError("a proposal needs one or more findings, each a text")
    for folder in (gallery.parent, gallery):
        if not _owned(folder, stat.S_IFDIR):
            raise ValueError(
                f"{folder} is no gallery directory of this user; run make design-gallery first"
            )
    target = gallery / PROPOSAL_FILE
    if target.is_symlink():
        raise ValueError(f"{target} is a symlink")
    shots = manifest(gallery)
    target.write_text(
        json.dumps({"findings": findings, "gaps": gaps(shots)}, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def proposed_apps(root: Path) -> frozenset[str]:
    """Return the apps whose gallery carries a proposal this user filed.

    Args:
        root: the gallery root.

    Returns:
        The app ids whose ``<root>/<app>/proposal.json`` is a regular file in a
        directory below ``root``, all three owned by this user; a symlink or
        another user's entry counts as missing.
    """
    if not _owned(root, stat.S_IFDIR):
        return frozenset()
    return frozenset(
        proposal.parent.name
        for proposal in root.glob(f"*/{PROPOSAL_FILE}")
        if _owned(proposal.parent, stat.S_IFDIR) and _owned(proposal, stat.S_IFREG)
    )
