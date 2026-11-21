from __future__ import annotations

import json
import re
import subprocess
from typing import TYPE_CHECKING

from utils.cache.evict import CacheConfigError, Usage

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_HUMAN_RE = re.compile(r"^\s*([\d.]+)\s*([kKMGTP]?)B\s*$")
_DECIMAL = {
    "": 1,
    "k": 10**3,
    "K": 10**3,
    "M": 10**6,
    "G": 10**9,
    "T": 10**12,
    "P": 10**15,
}


def parse_human_size(value: str) -> int:
    """Args:
        value: a decimal size as the Docker CLI prints it, as in ``28.5GB``.

    Returns:
        The size in bytes.

    Raises:
        CacheConfigError: the value names no size.
    """
    match = _HUMAN_RE.match(value)
    if match is None:
        raise CacheConfigError(f"'{value}' is no Docker size like 28.5GB")
    return int(float(match.group(1)) * _DECIMAL[match.group(2)])


def run_command(command: list[str]) -> str | None:
    """Args:
        command: the argv to run.

    Returns:
        Its stdout, or None when it cannot start, times out or exits non-zero.
    """
    try:
        done = subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=300
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def build_cache_usage(run: Callable[[list[str]], str | None]) -> Usage:
    """Args:
        run: runs a command and returns its stdout, or None when it fails.

    Returns:
        The size of the host Docker build cache; ``used`` is None without a reachable engine.
    """
    output = run(["docker", "system", "df", "--format", "{{json .}}"])
    if output is None:
        return Usage(used=None, complete=False)
    for line in output.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("Type") == "Build Cache":
            try:
                return Usage(
                    used=parse_human_size(str(row.get("Size", ""))), complete=True
                )
            except CacheConfigError:
                return Usage(used=None, complete=False)
    return Usage(used=0, complete=True)


def tools_running(run: Callable[[list[str]], str | None], models: Path) -> bool | None:
    """Args:
        run: runs a command and returns its stdout, or None when it fails.
        models: the models folder the tools lane mounts at the same path.

    Returns:
        Whether a running container mounts the models folder; None when the engine cannot tell.
    """
    output = run(["docker", "ps", "--quiet", "--filter", f"volume={models}"])
    if output is None:
        return None
    return bool(output.strip())
