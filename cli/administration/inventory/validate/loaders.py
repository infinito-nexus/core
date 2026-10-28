"""Inventory file I/O — YAML parsing + directory scans."""

from __future__ import annotations

import sys
from pathlib import Path

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str


def load_yaml_file(path):
    """Parse a YAML file; a ``!vault`` scalar loads as its ciphertext string.

    Args:
      path: the YAML file.

    Returns:
      the parsed document, or ``None`` after a warning when the file is
      missing or not valid YAML.
    """
    try:
        return load_yaml_str(read_text(str(path)))
    except Exception as e:
        print(f"Warning: Could not parse {path}: {e}", file=sys.stderr)
        return None


def load_inventory_files(inv_dir) -> dict[str, dict]:
    """Walk the inventory directory and collect every ``applications:``
    block keyed by its source file path."""
    all_data: dict[str, dict] = {}
    p = Path(inv_dir)
    for f in p.glob("*.yml"):
        data = load_yaml_file(f)
        if isinstance(data, dict):
            apps = data.get("applications")
            if apps:
                all_data[str(f)] = apps
    for d in p.glob("*_vars"):
        if d.is_dir():
            for f in d.rglob("*.yml"):
                data = load_yaml_file(f)
                if isinstance(data, dict):
                    apps = data.get("applications")
                    if apps:
                        all_data[str(f)] = apps
    return all_data
