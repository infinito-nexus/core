from pathlib import Path
from typing import Any

import yaml

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str

PROJECT_ROOT: Path = Path(__file__).resolve().parents[5]
ROLES_DIR: Path = PROJECT_ROOT / "roles"

__all__ = [
    "PROJECT_ROOT",
    "ROLES_DIR",
    "load_role_meta",
    "pin_line",
    "role_dirs",
    "variant_spans",
]


def role_dirs() -> list[Path]:
    """Every role directory under ``roles/``, sorted by name."""
    return sorted(path for path in ROLES_DIR.iterdir() if path.is_dir())


def variant_spans(lines: list[str]) -> list[range]:
    """The line range each top-level list entry occupies.

    Args:
        lines: the variants file's lines.
    """
    starts = [n for n, line in enumerate(lines, 1) if line.startswith("- ")]
    bounds = [*starts[1:], len(lines) + 1]
    return [range(start, end) for start, end in zip(starts, bounds, strict=True)]


def pin_line(lines: list[str], span: range, key: str) -> int | None:
    """The line declaring *key* inside one variant entry.

    Args:
        lines: the variants file's lines.
        span: the variant's line range.
        key: the service key to locate.
    """
    for number in span:
        if lines[number - 1].strip().startswith(f"{key}:"):
            return number
    return None


def load_role_meta(path: Path) -> Any:
    """Parse one role meta file.

    Args:
        path: the meta file to read.

    Returns:
        The parsed document, or ``None`` when the file is absent, empty,
        undecodable or not valid YAML.
    """
    if not path.is_file():
        return None
    try:
        text = read_text(str(path))
    except UnicodeDecodeError:
        return None
    if not text.strip():
        return None
    try:
        return load_yaml_str(text)
    except yaml.YAMLError:
        return None
