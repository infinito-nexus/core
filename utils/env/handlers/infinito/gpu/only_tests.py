"""INFINITO_TEST_GPU: whether the GPU-only tests run, true where
INFINITO_GPU_COUNT reserves a GPU; custom.env overrides it."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_TEST_GPU"
GPU_COUNT_KEY = "INFINITO_GPU_COUNT"
COMMENT = (
    "Run the GPU-only tests: true where INFINITO_GPU_COUNT reserves a GPU, else false."
)


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    reserves_gpu = eb.get(GPU_COUNT_KEY) not in ("", "0", "none")
    eb.setdefault(KEY, "true" if reserves_gpu else "false", comment=COMMENT)
