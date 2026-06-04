from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from . import PROJECT_ROOT
from .common import resolve_distro

if TYPE_CHECKING:
    import argparse


def _resolve_docker_root() -> Path:
    raw = (os.environ.get("INFINITO_DOCKER_VOLUME") or "").strip().rstrip("/")
    if not raw:
        raise RuntimeError("INFINITO_DOCKER_VOLUME must be set")
    return Path(raw)


def _wipe_docker_root(docker_root: Path) -> None:
    if not docker_root.exists():
        print(f">>> Docker root does not exist, nothing to clean: {docker_root}")
        return
    print(f">>> CI cleanup: wiping Docker root: {docker_root}")
    shutil.rmtree(docker_root, ignore_errors=True)
    docker_root.mkdir(parents=True, exist_ok=True)


def _should_wipe_docker_root() -> bool:
    if os.environ.get("INFINITO_RUNNING_ON_GITHUB") != "true":
        return False
    return os.environ.get("INFINITO_PRESERVE_DOCKER_CACHE") != "true"


def _cleanup_docker_root() -> None:
    if not _should_wipe_docker_root():
        docker_vol = os.environ.get("INFINITO_DOCKER_VOLUME") or "(unset)"
        print(f">>> Skipping Docker root wipe: {docker_vol}")
        return
    docker_root = _resolve_docker_root()
    _wipe_docker_root(docker_root)


def down_stack(*, repo_root: Path, distro: str) -> None:
    from .compose import Compose

    print(">>> Stopping compose stack and removing volumes")
    try:
        Compose(repo_root=repo_root, distro=distro).run(
            ["down", "--remove-orphans", "-v"]
        )
    finally:
        _cleanup_docker_root()


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("down", help="Stop compose stack and remove volumes.")
    p.set_defaults(_handler=handler)


def handler(args: argparse.Namespace) -> int:
    down_stack(repo_root=PROJECT_ROOT, distro=resolve_distro())
    return 0
