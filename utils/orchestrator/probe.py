"""The host and translation-lane load the cron tick folds into its actions.

Each tick reads ``/proc/stat`` and, when a lane container is named and the
``docker`` CLI is present, the lane's ``docker stats`` and ``docker top`` and
the GPU's ``nvidia-smi`` view, and pairs them with the previous tick into one
``sample.lane_sample``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from utils.orchestrator import sample

if TYPE_CHECKING:
    from collections.abc import Callable

    from utils.orchestrator.load import Load

PROC_STAT = Path("/proc/stat")
GPU_QUERY = (
    "nvidia-smi",
    "--query-gpu=utilization.gpu",
    "--format=csv,noheader,nounits",
)
GPU_PMON = ("nvidia-smi", "pmon", "-c", "1", "-s", "u")


def output(argv: list[str], timeout: int) -> str | None:
    """Return the stdout of ``argv``; None when its tool is absent, it fails
    or it times out.

    Args:
        argv: the command and its arguments.
        timeout: seconds the command may take.
    """
    if shutil.which(argv[0]) is None:
        return None
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def lane_load(
    previous: str | None,
    *,
    container: str | None,
    timeout: int,
    log: Callable[..., None],
) -> tuple[str, tuple[Load, Load] | None, bool]:
    """Return this tick's ``/proc/stat`` text, the lane sample paired with
    ``previous`` (None on the first tick, without a container or on an
    unreadable reading) and whether a GPU answered.

    Args:
        previous: the ``/proc/stat`` text of the last tick, None on the first.
        container: the translation lane container; empty measures nothing.
        timeout: seconds each CLI read may take.
        log: the server's event logger, told when a reading is unreadable.
    """
    with PROC_STAT.open(encoding="utf-8") as handle:
        current = handle.read()
    if previous is None or not container:
        return current, None, False
    stats = output(
        ["docker", "stats", "--no-stream", "--format", "{{json .}}"], timeout
    )
    top = output(["docker", "top", container, "-eo", "pid"], timeout)
    if stats is None or top is None:
        return current, None, False
    gpu_query = output(list(GPU_QUERY), timeout) or ""
    pmon = (output(list(GPU_PMON), timeout) or "") if gpu_query else ""
    try:
        pair = sample.lane_sample(
            stat_before=previous,
            stat_after=current,
            gpu_query=gpu_query,
            stats=stats,
            container=container,
            cpus=os.cpu_count(),
            pmon=pmon,
            top=top,
        )
    except (KeyError, ValueError, StopIteration) as error:
        log("load_unreadable", error=type(error).__name__)
        return current, None, False
    return current, pair, bool(gpu_query)
