"""INFINITO_PLAYWRIGHT_REPORTS_BASE_DIR: per-app Playwright reports root,
derived from the var-lib SPOT (INFINITO_DIR_VAR_LIB)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_PLAYWRIGHT_REPORTS_BASE_DIR"
COMMENT = (
    "Host dir where the test-e2e-playwright role writes per-app reports "
    "(derived from INFINITO_DIR_VAR_LIB)."
)


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    base = eb.get("INFINITO_DIR_VAR_LIB")
    eb.set(KEY, f"{base}/logs/test-e2e-playwright", comment=COMMENT)
