"""Inventory file I/O — YAML parsing with vault stripping + directory scans."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str

_VAULT_BLOCK_RE = re.compile(r"(?m)^([ \t]*[^\s:]+):\s*!vault[\s\S]+?(?=^\S|\Z)")


def load_yaml_file(path):
    """Parse a YAML file, replacing ``!vault`` scalars with a placeholder.

    The cache's path-keyed loader is bypassed on purpose — the caller
    mutates content per call, so each parse is intentionally fresh.
    """
    try:
        content = read_text(str(path))
        content = _VAULT_BLOCK_RE.sub(r'\1: "<vaulted>"\n', content)
        return load_yaml_str(content)
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
