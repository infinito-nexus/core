"""Install hadolint via GitHub-release prebuilt binary."""

from __future__ import annotations

import os
import platform
import tempfile
from pathlib import Path

from utils.install.github_release import download_release_asset, resolve_latest_tag
from utils.install.primitives import (
    ensure_dir_on_path,
    install_with_optional_sudo,
    log,
    which,
)

_LATEST_URL = "https://github.com/hadolint/hadolint/releases/latest"
_DEFAULT_INSTALL_DIR = os.environ.get("HADOLINT_INSTALL_DIR", "/usr/local/bin")


def _detect_os() -> str:
    system = platform.system()
    if system == "Linux":
        return "Linux"
    if system == "Darwin":
        return "Darwin"
    raise RuntimeError(f"Unsupported OS for hadolint prebuilt binary: {system}")


def _detect_arch() -> str:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "x86_64"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    raise RuntimeError(
        f"Unsupported architecture for hadolint prebuilt binary: {machine}"
    )


def _resolve_version() -> str:
    requested = os.environ.get("HADOLINT_VERSION", "latest").lstrip("v")
    if requested != "latest":
        return requested
    return resolve_latest_tag(_LATEST_URL)


def _install_binary() -> None:
    version = _resolve_version()
    asset_name = f"hadolint-{_detect_os()}-{_detect_arch()}"
    url = f"https://github.com/hadolint/hadolint/releases/download/v{version}/{asset_name}"

    log(f"Installing hadolint v{version} from GitHub releases")

    with tempfile.TemporaryDirectory() as tmpdir:
        binary_src = Path(tmpdir) / "hadolint"
        download_release_asset(url, str(binary_src))

        install_with_optional_sudo(["install", "-d", _DEFAULT_INSTALL_DIR])
        dst = str(Path(_DEFAULT_INSTALL_DIR) / "hadolint")
        install_with_optional_sudo(["install", "-m", "0755", str(binary_src), dst])


def ensure() -> None:
    if which("hadolint"):
        return

    log("Missing command 'hadolint'. Installing official prebuilt binary.")
    _install_binary()
    ensure_dir_on_path(_DEFAULT_INSTALL_DIR)

    if not which("hadolint"):
        raise RuntimeError(
            "Command 'hadolint' is still unavailable after installation."
        )
