"""Install shfmt: system-pkg first, GitHub release fallback."""

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
from utils.install.system_pkg import detect_package_manager, install_command_via_pkg

_LATEST_URL = "https://github.com/mvdan/sh/releases/latest"
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


def _resolve_version() -> str:
    requested = os.environ.get("SHFMT_VERSION", "latest").lstrip("v")
    if requested != "latest":
        return requested
    return resolve_latest_tag(_LATEST_URL)


def _install_binary() -> None:
    version = _resolve_version()
    os_name = _detect_os()
    arch = _detect_arch()
    asset_name = f"shfmt_v{version}_{os_name}_{arch}"
    url = f"https://github.com/mvdan/sh/releases/download/v{version}/{asset_name}"

    if os.environ.get("SHFMT_VERSION", "latest").lstrip("v") == "latest":
        log(f"Installing latest shfmt (resolved to v{version}) from GitHub releases")
    else:
        log(f"Installing shfmt v{version} from GitHub releases")

    with tempfile.TemporaryDirectory() as tmpdir:
        binary_path = str(Path(tmpdir) / "shfmt")
        download_release_asset(url, binary_path)

        install_with_optional_sudo(["install", "-d", _DEFAULT_INSTALL_DIR])
        dst = str(Path(_DEFAULT_INSTALL_DIR) / "shfmt")
        install_with_optional_sudo(["install", "-m", "0755", binary_path, dst])

    ensure_dir_on_path(_DEFAULT_INSTALL_DIR)


def ensure() -> None:
    if which("shfmt"):
        return

    log("Missing command 'shfmt'. Attempting system package installation.")
    try:
        manager = detect_package_manager()
        try:
            install_command_via_pkg("shfmt")
        except RuntimeError as exc:
            log(f"System package install failed for 'shfmt' via {manager}: {exc}")
    except RuntimeError:
        log(
            "No supported package manager found; falling back to GitHub release binary."
        )

    if which("shfmt"):
        return

    log("Falling back to official shfmt binary.")
    _install_binary()

    if not which("shfmt"):
        raise RuntimeError("Command 'shfmt' is still unavailable after installation.")
