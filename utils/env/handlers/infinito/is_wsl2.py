"""INFINITO_IS_WSL2: true when /proc/version identifies the host as WSL2."""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.env.runtime import is_wsl2

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_IS_WSL2"
COMMENT = "True when /proc/version identifies the host as WSL2."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.set(KEY, "true" if is_wsl2() else "false", comment=COMMENT)
