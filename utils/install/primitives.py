"""Shared low-level install helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.request import urlopen

if TYPE_CHECKING:
    from collections.abc import Sequence


def log(msg: str) -> None:
    print(msg, flush=True)


def warn(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def which(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def run_privileged(cmd: Sequence[str]) -> None:
    argv: list[str] = list(cmd)
    if os.geteuid() != 0 and shutil.which("sudo") is not None:
        argv = ["sudo", *argv]
    subprocess.run(argv, check=True)


def ensure_dir_on_path(directory: str) -> None:
    if not directory:
        return
    current = os.environ.get("PATH", "")
    parts = current.split(os.pathsep) if current else []
    if directory in parts:
        return
    os.environ["PATH"] = directory + (os.pathsep + current if current else "")


def download_file(url: str, output: str, *, timeout: float = 60.0) -> None:
    with urlopen(url, timeout=timeout) as response:  # noqa: S310 - trusted release URLs only
        data = response.read()
    Path(output).write_bytes(data)


def install_with_optional_sudo(cmd: Sequence[str]) -> None:
    argv = list(cmd)
    try:
        subprocess.run(argv, check=True)
    except subprocess.CalledProcessError:
        run_privileged(argv)
