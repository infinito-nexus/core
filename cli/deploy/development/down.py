from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

from .common import cache_env_overrides, compose_file_args, resolve_distro
from .profile import Profile


def _repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[3]


CI_DOCKER_ROOT = Path("/mnt/docker")


def _base_env(*, distro: str) -> dict[str, str]:
    env = dict(os.environ)
    env["INFINITO_DISTRO"] = distro
    env.update(cache_env_overrides())
    return env


def _compose_run(*, repo_root: Path, distro: str, args: list[str]) -> None:
    cmd = ["docker", "compose", "--env-file", "env.ci"]
    env_development = repo_root / "env.development"
    if env_development.exists():
        cmd += ["--env-file", "env.development"]

    cmd += compose_file_args()
    cmd += Profile().args()
    cmd += list(args)
    env = _base_env(distro=distro)
    env.setdefault("NIX_CONFIG", "")
    subprocess.run(cmd, cwd=repo_root, env=env, check=True, text=True)


def _cleanup_docker_root() -> None:
    if os.environ.get("RUNNING_ON_GITHUB") != "true":
        print(f">>> Not on GitHub - No bind volumes will be deleted: {CI_DOCKER_ROOT}")
        return

    if os.environ.get("INFINITO_PRESERVE_DOCKER_CACHE", "false").lower() == "true":
        print(
            ">>> INFINITO_PRESERVE_DOCKER_CACHE=true — keeping Docker root for next distro"
        )
        return

    docker_root_env = os.environ.get("INFINITO_DOCKER_VOLUME", "").strip().rstrip("/")
    docker_root = Path(docker_root_env) if docker_root_env else CI_DOCKER_ROOT

    # Allow /mnt/docker itself and any per-runner subdirectory (e.g. /mnt/docker/1).
    try:
        docker_root.relative_to(CI_DOCKER_ROOT)
    except ValueError:
        raise RuntimeError(
            "SECURITY VIOLATION: "
            f"INFINITO_DOCKER_VOLUME={docker_root} is not allowed on GitHub runner. "
            f"Only {CI_DOCKER_ROOT} or subdirectories are permitted."
        )

    if not docker_root.exists():
        print(f">>> Docker root does not exist, nothing to clean: {docker_root}")
        return

    print(f">>> CI cleanup: wiping Docker root: {docker_root}")
    shutil.rmtree(docker_root, ignore_errors=True)
    docker_root.mkdir(parents=True, exist_ok=True)


def down_stack(*, repo_root: Path, distro: str) -> None:
    print(">>> Stopping compose stack and removing volumes")
    try:
        _compose_run(
            repo_root=repo_root,
            distro=distro,
            args=["down", "--remove-orphans", "-v"],
        )
    finally:
        _cleanup_docker_root()


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("down", help="Stop compose stack and remove volumes.")
    p.set_defaults(_handler=handler)


def handler(args: argparse.Namespace) -> int:
    down_stack(repo_root=_repo_root_from_here(), distro=resolve_distro())
    return 0
