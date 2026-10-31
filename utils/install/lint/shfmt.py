"""Install shfmt via GitHub-release prebuilt binary."""

from __future__ import annotations

import os
import platform
import subprocess
import tempfile
from pathlib import Path

from utils.install.github_release import download_release_asset
from utils.install.lint.pinned import resolve_release
from utils.install.primitives import (
    ensure_dir_on_path,
    install_with_optional_sudo,
    log,
)

# nocheck: environ-get-default  contributor tooling, never deployed: no inventory or image declares SHFMT_INSTALL_DIR, it only lets a workstation without write access to /usr/local/bin redirect the binary
_DEFAULT_INSTALL_DIR = os.environ.get("SHFMT_INSTALL_DIR", "/usr/local/bin")


def _detect_os() -> str:
    system = platform.system()
    if system == "Linux":
        return "linux"
    if system == "Darwin":
        return "darwin"
    raise RuntimeError(f"Unsupported OS for shfmt prebuilt binary: {system}")


def _detect_arch() -> str:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("i386", "i486", "i586", "i686"):
        return "386"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    if machine in ("armv6l", "armv7l"):
        return "arm"
    raise RuntimeError(f"Unsupported architecture for shfmt prebuilt binary: {machine}")


def _install_binary() -> None:
    slug, version = resolve_release("shfmt")
    os_name = _detect_os()
    arch = _detect_arch()
    asset_name = f"shfmt_v{version}_{os_name}_{arch}"
    url = f"https://github.com/{slug}/releases/download/v{version}/{asset_name}"

    log(f"Installing shfmt v{version} from GitHub releases")

    with tempfile.TemporaryDirectory() as tmpdir:
        binary_path = str(Path(tmpdir) / "shfmt")
        download_release_asset(url, binary_path)

        install_with_optional_sudo(["install", "-d", _DEFAULT_INSTALL_DIR])
        dst = str(Path(_DEFAULT_INSTALL_DIR) / "shfmt")
        install_with_optional_sudo(["install", "-m", "0755", binary_path, dst])

    ensure_dir_on_path(_DEFAULT_INSTALL_DIR)


def _installed_version() -> str | None:
    try:
        proc = subprocess.run(
            ["shfmt", "--version"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return proc.stdout.strip().lstrip("v") or None


def ensure() -> None:
    _slug, want = resolve_release("shfmt")
    found = _installed_version()
    if found == want:
        return

    log(f"Installing shfmt v{want} (found {found or 'no shfmt'}).")
    _install_binary()

    found = _installed_version()
    if found != want:
        raise RuntimeError(
            f"Command 'shfmt' reports {found or 'nothing'} after installing "
            f"v{want} into {_DEFAULT_INSTALL_DIR}; that directory must precede "
            "any other shfmt on PATH."
        )
