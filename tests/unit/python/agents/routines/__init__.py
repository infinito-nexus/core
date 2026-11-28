from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def written_text(path: Path) -> str:
    """Return the text the code under test has just written to ``path``.

    Args:
        path: a ledger or state file inside the test's temporary directory.
    """
    return path.read_text(
        encoding="utf-8"
    )  # nocheck: cache-read  ledger and state files the code under test writes in the same test
