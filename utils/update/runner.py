"""Bump the pinned GitHub-hosted Ubuntu runner label of every workflow job.

GitHub lists its hosted images in the runner-images README; the newest x64
Ubuntu label whose image carries no preview or beta badge is the target.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

IMAGES_README = "https://raw.githubusercontent.com/actions/runner-images/main/README.md"

_LABEL = re.compile(r"`ubuntu-(\d{2})\.(\d{2})`")
_RUNS_ON = re.compile(r"(runs-on:\s*)ubuntu-(\d{2})\.(\d{2})(?![\w.-])")
_PRERELEASE = re.compile(r"preview|beta", re.IGNORECASE)


def newest_ubuntu_label(readme: str) -> str | None:
    """Return the newest GA x64 Ubuntu label listed in the images table.

    Args:
        readme: text of the runner-images README.
    """
    versions: list[tuple[int, int]] = []
    for row in readme.splitlines():
        cells = [cell.strip() for cell in row.split("|")]
        if len(cells) < 5 or not cells[1].startswith("Ubuntu"):
            continue
        if _PRERELEASE.search(cells[1]) or cells[2] != "x64":
            continue
        versions += [
            (int(major), int(minor)) for major, minor in _LABEL.findall(cells[3])
        ]
    if not versions:
        return None
    major, minor = max(versions)
    return f"ubuntu-{major:02d}.{minor:02d}"


def bump_text(text: str, label: str) -> str:
    """Raise every older ``runs-on: ubuntu-NN.NN`` in *text* to *label*.

    Args:
        text: workflow source.
        label: target label, ``ubuntu-NN.NN``.
    """
    target = tuple(int(part) for part in label.removeprefix("ubuntu-").split("."))

    def _raise(match: re.Match[str]) -> str:
        if (int(match.group(2)), int(match.group(3))) < target:
            return match.group(1) + label
        return match.group(0)

    return _RUNS_ON.sub(_raise, text)


def bump_workflows(workflows_dir: Path, label: str) -> list[Path]:
    """Rewrite the workflows under *workflows_dir* to *label*; return the changed files.

    Args:
        workflows_dir: directory holding the workflow YAML files.
        label: target label, ``ubuntu-NN.NN``.
    """
    changed: list[Path] = []
    for path in sorted(workflows_dir.glob("*.y*ml")):
        text = path.read_text(  # nocheck: cache-read — read-then-write of the same file; cached read would go stale
            encoding="utf-8"
        )
        bumped = bump_text(text, label)
        if bumped != text:
            path.write_text(bumped, encoding="utf-8")
            changed.append(path)
    return changed
