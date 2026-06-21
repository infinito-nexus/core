"""INFINITO_VARIANT_TIME_OVERFLOW: how the variant-iteration guard reacts when
the remaining rounds no longer fit INFINITO_MAX_RUNTIME — ``cut`` (warn + skip)
or ``fail`` (abort the deploy). Defaults to ``cut`` everywhere."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_VARIANT_TIME_OVERFLOW"
COMMENT = (
    "Variant-iteration budget overflow policy "
    "(cli.administration.deploy.development): cut = warn and skip the rounds "
    "that no longer fit INFINITO_MAX_RUNTIME; fail = abort the deploy instead."
)


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.setdefault(KEY, "cut", comment=COMMENT)
