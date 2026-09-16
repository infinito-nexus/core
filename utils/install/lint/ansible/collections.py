"""Install required Ansible collections via ansible-galaxy with retry + git fallback."""

from __future__ import annotations

import random
import subprocess
import time
from pathlib import Path

from utils.cache import PROJECT_ROOT
from utils.install.collections import unsatisfied
from utils.install.primitives import log, warn

_MAX_ATTEMPTS = 5


def _galaxy_install(requirements_file: Path, base_dir: Path) -> bool:
    try:
        subprocess.run(
            [
                "ansible-galaxy",
                "collection",
                "install",
                "-r",
                str(requirements_file),
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
    repo_root = Path(PROJECT_ROOT)
    req_galaxy = repo_root / "requirements" / "requirements.galaxy.yml"
    req_git = repo_root / "requirements" / "requirements.git.yml"

    missing = unsatisfied(req_galaxy, collections_base_dir)
    if not missing:
        return

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
