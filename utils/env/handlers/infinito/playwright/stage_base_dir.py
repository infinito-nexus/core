"""INFINITO_PLAYWRIGHT_STAGE_BASE_DIR: host dir where Playwright projects
are staged per role, read from the test-e2e-playwright role vars SPOT
(``TEST_E2E_PLAYWRIGHT_STAGE_BASE_DIR``)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_PLAYWRIGHT_STAGE_BASE_DIR"
COMMENT = (
    "Host dir where Playwright projects are staged per role (SPOT: "
    "roles/test-e2e-playwright/vars/main.yml)."
)
_ROLE_VARS = PROJECT_ROOT / "roles" / "test-e2e-playwright" / ROLE_FILE_VARS_MAIN
_SPOT_KEY = "TEST_E2E_PLAYWRIGHT_STAGE_BASE_DIR"


def _stage_base() -> str:
    """Line parse, stdlib-only on purpose: this SPOT feeds the .env
    generation, which bootstraps fresh hosts before PyYAML exists."""
    for line in read_text(str(_ROLE_VARS)).splitlines():
        if not line.startswith(f"{_SPOT_KEY}:"):
            continue
        value = line.split(":", 1)[1].split("#", 1)[0].strip()
        return value.strip("\"'")
    raise RuntimeError(f"{_SPOT_KEY} not found in {_ROLE_VARS}")


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.setdefault(KEY, _stage_base(), comment=COMMENT)
