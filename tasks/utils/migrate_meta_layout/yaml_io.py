from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict

import yaml


def load(path: Path) -> Any:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return None
    return yaml.safe_load(text)  # noqa: direct-yaml — once-off migration script


def dump(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(  # noqa: direct-yaml — once-off migration script
        data if data is not None else {},
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=4096,
    )
    path.write_text(text, encoding="utf-8")


def empty_dir(path: Path) -> None:
    if not path.is_dir():
        return
    for child in path.iterdir():
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)
    path.rmdir()


def deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged: Dict[str, Any] = dict(base)
        for key, value in override.items():
            merged[key] = deep_merge(merged[key], value) if key in merged else value
        return merged
    return override
