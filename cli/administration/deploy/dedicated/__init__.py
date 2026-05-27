from __future__ import annotations

from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[4]

from .command import main  # noqa: E402
from .modes import _parse_bool_literal  # noqa: E402

__all__ = ["PROJECT_ROOT", "_parse_bool_literal", "main"]
