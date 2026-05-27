"""npm-based installer helpers."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from utils.install.primitives import ensure_dir_on_path, install_with_optional_sudo, log


def ensure_npm_present() -> None:
    if shutil.which("npm") is not None:
        return

    log("npm missing; attempting Node.js/npm install via system package manager.")
    from utils.install.system_pkg import install_command_via_pkg

    install_command_via_pkg("npm")

    if shutil.which("npm") is None:
        raise RuntimeError("npm not found and could not be installed")


def npm_install_global(package: str) -> None:
    ensure_npm_present()
    log(f"Installing '{package}' via npm (global)")
    try:
        install_with_optional_sudo(["npm", "install", "-g", package])
    except subprocess.CalledProcessError:
        pass
    else:
        return

    prefix = Path("~/.npm-global").expanduser()
    prefix.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["npm", "install", "-g", "--prefix", str(prefix), package],
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"npm install -g {package} failed (both global and --prefix)"
        ) from exc
    ensure_dir_on_path(str(prefix / "bin"))


def npm_install_local_in_repo(repo_root: str) -> None:
    ensure_npm_present()
    has_lock = (Path(repo_root) / "package-lock.json").is_file()
    argv = (
        ["npm", "ci", "--no-fund", "--no-audit"]
        if has_lock
        else ["npm", "install", "--no-fund", "--no-audit"]
    )
    try:
        subprocess.run(argv, check=True, cwd=repo_root)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"npm install in {repo_root} failed") from exc


__all__ = ["ensure_npm_present", "npm_install_global", "npm_install_local_in_repo"]
