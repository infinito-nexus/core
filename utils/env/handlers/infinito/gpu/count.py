"""INFINITO_GPU_COUNT: GPUs the compose services reserve, 'all' when the docker
daemon registers an NVIDIA runtime, else 0."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_GPU_COUNT"
COMMENT = "GPUs the compose services reserve: 'all' on an NVIDIA host, else 0."


def _runtimes() -> str:
    try:
        return subprocess.run(
            ["docker", "info", "--format", "{{json .Runtimes}}"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
    except OSError:
        return ""


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.setdefault(KEY, "all" if "nvidia" in _runtimes() else "0", comment=COMMENT)
