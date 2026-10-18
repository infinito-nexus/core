from pathlib import Path
from typing import Any

import yaml

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str

PROJECT_ROOT: Path = Path(__file__).resolve().parents[5]
ROLES_DIR: Path = PROJECT_ROOT / "roles"


def role_dirs() -> list[Path]:
    """Every role directory under ``roles/``, sorted by name."""
    return sorted(path for path in ROLES_DIR.iterdir() if path.is_dir())


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
