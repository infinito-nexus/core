"""Shared low-level install helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from http.client import HTTPException
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.error import HTTPError
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


_DOWNLOAD_ATTEMPTS = 4
_RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})


def ensure_dir_on_path(directory: str) -> None:
    if not directory:
        return
    current = os.environ.get("PATH", "")
    parts = current.split(os.pathsep) if current else []
    if directory in parts:
        return
    os.environ["PATH"] = directory + (os.pathsep + current if current else "")


def download_file(url: str, output: str, *, timeout: float = 60.0) -> None:
    """Fetch *url* into *output*, retrying only transient transport failures.

    Args:
        url: source to read.
        output: path the body is written to.
        timeout: per-attempt socket timeout in seconds.

    Raises:
        HTTPError: immediately for any status outside _RETRYABLE_STATUS, so a
            stale version pin fails on the first attempt instead of after the
            backoff.
    """
    for attempt in range(1, _DOWNLOAD_ATTEMPTS + 1):
        try:
            with urlopen(url, timeout=timeout) as response:  # noqa: S310 - trusted release URLs only
                data = response.read()
        except HTTPError as err:
            if err.code not in _RETRYABLE_STATUS or attempt == _DOWNLOAD_ATTEMPTS:
                raise
            reason = f"HTTP {err.code}"
        except (OSError, HTTPException) as err:
            if attempt == _DOWNLOAD_ATTEMPTS:
                raise
            reason = type(err).__name__
        else:
            Path(output).write_bytes(data)
            return
        warn(f"{url}: {reason}; retrying in {2**attempt}s")
        time.sleep(2**attempt)


def install_with_optional_sudo(cmd: Sequence[str]) -> None:
    argv = list(cmd)
    try:
        subprocess.run(argv, check=True)
    except subprocess.CalledProcessError:
        run_privileged(argv)
