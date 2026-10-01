"""INFINITO_I18N_BATCH_SIZE / INFINITO_I18N_LANES: client settings `make
i18n-tune` measured on this host, falling back to the shipped defaults."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from utils.cache.files import read_text
from utils.i18n.limits import BATCH_SIZE

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

TUNING_FILE = Path("build") / "i18n-tuning.json"
BATCH_KEY = "INFINITO_I18N_BATCH_SIZE"
LANES_KEY = "INFINITO_I18N_LANES"
BATCH_COMMENT = "Texts per LibreTranslate request; `make i18n-tune` measures it."
LANES_COMMENT = "Concurrent LibreTranslate requests; 0 derives from the CPU count."


def measured(repo_root: Path) -> dict:
    """Return the winning pair `make i18n-tune` recorded, empty when absent."""
    path = repo_root / TUNING_FILE
    if not path.is_file():
        return {}
    try:
        return json.loads(read_text(str(path))).get("best") or {}
    except (OSError, ValueError):
        return {}


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    best = measured(ctx.repo_root)
    eb.setdefault(
        BATCH_KEY, str(best.get("batch_size", BATCH_SIZE)), comment=BATCH_COMMENT
    )
    eb.setdefault(LANES_KEY, str(best.get("lanes", 0)), comment=LANES_COMMENT)
