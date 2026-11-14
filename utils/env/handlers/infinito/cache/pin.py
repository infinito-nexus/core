from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.context import BuildContext, EnvBuilder

KEY = "INFINITO_CACHE_PIN_FILE"
ROOT_KEY = "INFINITO_CACHE_PIN_ROOT"
STATIC_READS = (KEY, ROOT_KEY)


def xdg_dir(variable: str, fallback: tuple[str, ...]) -> Path:
    """Return an XDG base directory, as the XDG specification resolves it.

    Args:
        variable: XDG_STATE_HOME or XDG_DATA_HOME.
        fallback: the legs below HOME the specification names for an unset
            or relative value.
    """
    value = os.environ.get(variable, "").strip()
    if value and Path(value).is_absolute():
        return Path(value)
    return Path.home().joinpath(*fallback)


def _setdefault(eb: EnvBuilder, ctx: BuildContext, key: str, derived: Path) -> None:
    fallback = ctx.static.get(key, "") or str(derived)
    eb.setdefault(key, fallback, comment=ctx.static_comments.get(key, ""))


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    state = xdg_dir("XDG_STATE_HOME", (".local", "state"))
    data = xdg_dir("XDG_DATA_HOME", (".local", "share"))
    _setdefault(eb, ctx, KEY, state / "infinito" / "cache.ref")
    _setdefault(eb, ctx, ROOT_KEY, data / "infinito" / "cache")
