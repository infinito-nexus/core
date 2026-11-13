"""The level each language's catalogs were last accepted at, and the gate on it.

A language's level is the mean of the levels the chat judge placed its sampled
entries on. The store lives in ``build/i18n`` on the host that runs the judge
pass, so a host without one accepts its first pass as the baseline.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

ACCEPTED_FILE = ("build", "i18n", "accepted-levels.json")


def accepted_levels(root: Path) -> dict[str, float]:
    """Return the level each language was last accepted at.

    Args:
        root: repository root.
    """
    path = root.joinpath(*ACCEPTED_FILE)
    if not path.is_file():
        return {}
    text = path.read_text(
        encoding="utf-8"
    )  # nocheck: cache-read  gate() rewrites this file and the next language re-reads it in the same process
    return json.loads(text)


def gate(root: Path, code: str, levels: Sequence[int], aborted: str = "") -> str:
    """Return why ``code`` gets no pull request, empty when it passes.

    A pass becomes the language's accepted level; a refusal leaves the stored
    level as it was, so a slow decline cannot ratchet the baseline down.

    Args:
        root: repository root.
        code: ISO 639-1 code of the language.
        levels: the level of every sample the judge answered.
        aborted: the error of a judge reply that named no level, empty when
            every reply named one. It aborts the verification: the levels
            gathered before it are not scored.
    """
    if aborted:
        return f"verification aborted: {aborted}"
    if not levels:
        return "no sample reached a level"
    level = sum(levels) / len(levels)
    accepted = accepted_levels(root)
    last = accepted.get(code)
    if last is not None and level < last:
        return f"sampled level {level:.2f} is below its last accepted level {last:.2f}"
    accepted[code] = level
    path = root.joinpath(*ACCEPTED_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(accepted, indent=2, sort_keys=True) + "\n", "utf-8")
    return ""
