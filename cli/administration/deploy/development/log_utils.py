from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def log_path(logs_dir: Path, deploy_type: str, distro: str, suffix: str) -> Path:
    return logs_dir / f"deploy-{deploy_type}-{distro}-{suffix}.log"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def append_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if path.exists():
        existing = path.read_text(
            encoding="utf-8", errors="replace"
        )  # nocheck: cache-read — append flow: reads existing then rewrites with appended text; cache would return pre-append content on subsequent calls
    path.write_text(existing + text, encoding="utf-8")
