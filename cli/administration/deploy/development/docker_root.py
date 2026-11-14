from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .profile import Profile


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
    subprocess.run(["sudo", "rm", "-rf", str(docker_root)], check=True)
    subprocess.run(["sudo", "mkdir", "-p", str(docker_root)], check=True)
    subprocess.run(
        ["sudo", "chown", f"{os.getuid()}:{os.getgid()}", str(docker_root)],
        check=True,
    )
    leftovers = sorted(entry.name for entry in docker_root.iterdir())
    if leftovers:
        raise RuntimeError(
            f"Docker root survived the wipe: {docker_root} still holds {leftovers}"
        )


def _should_wipe_docker_root() -> bool:
    if not Profile().docker_root_ephemeral():
        return False
    return os.environ.get("INFINITO_PRESERVE_DOCKER_CACHE") != "true"


def cleanup_docker_root() -> None:
    if not _should_wipe_docker_root():
        docker_vol = os.environ.get("INFINITO_DOCKER_VOLUME") or "(unset)"
        print(f">>> Skipping Docker root wipe: {docker_vol}")
        return
    docker_root = _resolve_docker_root()
    _wipe_docker_root(docker_root)
