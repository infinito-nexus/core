"""The Python 3 minors core runs on, read from ``requires-python`` of pyproject.toml."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text

FOLLOW = "requires-python"
_RANGE = re.compile(r"^>=3\.(\d+),<3\.(\d+)$")


def requires_python(root: Path = PROJECT_ROOT) -> str:
    """Return the ``requires-python`` spec of ``<root>/pyproject.toml``.

    Args:
        root: the repository root holding pyproject.toml.
    """
    pyproject = tomllib.loads(read_text(str(Path(root) / "pyproject.toml")))
    return str(pyproject["project"]["requires-python"])


def supported_minors(spec: str) -> range:
    """Return the Python 3 minors a ``>=3.X,<3.Y`` spec admits.

    Args:
        spec: the ``requires-python`` value.

    Raises:
        ValueError: the spec has another shape.
    """
    match = _RANGE.fullmatch(spec)
    if match is None:
        raise ValueError(f"requires-python {spec!r} must read >=3.X,<3.Y")
    return range(int(match[1]), int(match[2]))
