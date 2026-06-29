"""Install actionlint via GitHub-release prebuilt binary."""

from __future__ import annotations

import os
import platform
import tarfile
import tempfile
from pathlib import Path

from utils.install.github_release import download_release_asset, resolve_latest_tag
from utils.install.primitives import (
    ensure_dir_on_path,
    install_with_optional_sudo,
    log,
    which,
)

_LATEST_URL = "https://github.com/rhysd/actionlint/releases/latest"
_DEFAULT_INSTALL_DIR = os.environ.get("ACTIONLINT_INSTALL_DIR", "/usr/local/bin")


def _detect_os() -> str:
    system = platform.system()
    if system == "Linux":
        return "linux"
    if system == "Darwin":
        return "darwin"
    if system == "FreeBSD":
        return "freebsd"
    raise RuntimeError(f"Unsupported OS for actionlint prebuilt binary: {system}")


def _detect_arch() -> str:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("i386", "i486", "i586", "i686"):
        return "386"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    if machine in ("armv6l", "armv7l"):
        return "armv6"
    raise RuntimeError(
        f"Unsupported architecture for actionlint prebuilt binary: {machine}"
    )


def _resolve_version() -> str:
    requested = os.environ.get("ACTIONLINT_VERSION", "latest").lstrip("v")
    if requested != "latest":
        return requested
    return resolve_latest_tag(_LATEST_URL)


def _install_binary() -> None:
    version = _resolve_version()
    os_name = _detect_os()
    arch = _detect_arch()
    archive_name = f"actionlint_{version}_{os_name}_{arch}.tar.gz"
    url = f"https://github.com/rhysd/actionlint/releases/download/v{version}/{archive_name}"

    if os.environ.get("ACTIONLINT_VERSION", "latest").lstrip("v") == "latest":
        log(
            f"Installing latest actionlint (resolved to v{version}) from GitHub releases"
        )
    else:
        log(f"Installing actionlint v{version} from GitHub releases")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        archive_path = tmp_path / archive_name
        download_release_asset(url, str(archive_path))

        with tarfile.open(archive_path) as tar:
            dest_root = tmp_path.resolve()
            for member in tar.getmembers():
                member_path = (tmp_path / member.name).resolve()
                if not member_path.is_relative_to(dest_root):
                    raise RuntimeError(
                        f"Archive {archive_name} contains an unsafe path: {member.name}"
                    )
            tar.extractall(tmpdir)  # noqa: S202 - members validated for path traversal

        binary_src = tmp_path / "actionlint"
        if not binary_src.is_file():
            raise RuntimeError(
                f"Archive {archive_name} did not contain an actionlint binary."
            )

        install_with_optional_sudo(["install", "-d", _DEFAULT_INSTALL_DIR])
        dst = str(Path(_DEFAULT_INSTALL_DIR) / "actionlint")
        install_with_optional_sudo(["install", "-m", "0755", str(binary_src), dst])


def ensure() -> None:
    if which("actionlint"):
        return

    log("Missing command 'actionlint'. Installing official prebuilt binary.")
    _install_binary()
    ensure_dir_on_path(_DEFAULT_INSTALL_DIR)

    if not which("actionlint"):
        raise RuntimeError(
            "Command 'actionlint' is still unavailable after installation."
        )
