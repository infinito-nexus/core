"""Install required Ansible collections via ansible-galaxy with retry + git fallback."""

from __future__ import annotations

import random
import subprocess
import time
from pathlib import Path

from utils.cache import PROJECT_ROOT
from utils.install.primitives import log, warn

_MAX_ATTEMPTS = 5


def _collection_present(base_dir: Path, namespace: str, name: str) -> bool:
    return (base_dir / "ansible_collections" / namespace / name).is_dir()


def _galaxy_install(requirements_file: str, base_dir: Path) -> bool:
    try:
        subprocess.run(
            [
                "ansible-galaxy",
                "collection",
                "install",
                "-r",
                requirements_file,
                "-p",
                str(base_dir),
                "--force-with-deps",
            ],
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return True


def ensure() -> None:
    collections_base_dir = Path("~/.ansible/collections").expanduser()
    missing: list[str] = []

    if not _collection_present(collections_base_dir, "community", "general"):
        missing.append("community.general")
    if not _collection_present(collections_base_dir, "hetzner", "hcloud"):
        missing.append("hetzner.hcloud")
    if not _collection_present(collections_base_dir, "kewlfft", "aur"):
        missing.append("kewlfft.aur")

    if not missing:
        return

    repo_root = Path(PROJECT_ROOT)
    req_galaxy = str(repo_root / "requirements" / "requirements.galaxy.yml")
    req_git = str(repo_root / "requirements" / "requirements.git.yml")

    attempt = 1
    while True:
        log(
            f"Installing missing Ansible collections: {' '.join(missing)} "
            f"(attempt {attempt}/{_MAX_ATTEMPTS})"
        )

        if _galaxy_install(req_galaxy, collections_base_dir):
            return

        warn(f"Galaxy install failed on attempt {attempt}. Trying git fallback.")
        if _galaxy_install(req_git, collections_base_dir):
            return

        if attempt >= _MAX_ATTEMPTS:
            raise RuntimeError("Unable to install required Ansible collections.")

        sleep_time = 60 + random.randint(0, 60)  # noqa: S311 - jitter, not crypto
        warn(f"Retrying collection installation in {sleep_time}s.")
        time.sleep(sleep_time)
        attempt += 1
