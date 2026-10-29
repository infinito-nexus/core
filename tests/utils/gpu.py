"""Whether the GPU-only tests run on this host."""

from __future__ import annotations

import os

from utils.i18n.libretranslate import accelerated

FLAG = "INFINITO_TEST_GPU"


def gpu_tests_enabled() -> bool:
    """Read ``INFINITO_TEST_GPU``, which ``make dotenv`` derives from the GPU count and ``custom.env`` overrides.

    Returns:
        The flag. Where the env was not loaded, the same derivation the
        handler uses: whether Docker can hand a GPU to a container.

    Raises:
        ValueError: the flag is neither ``true`` nor ``false``.
    """
    raw = (os.environ.get(FLAG) or "").strip().lower()
    if not raw:
        return accelerated()
    if raw not in ("true", "false"):
        raise ValueError(f"{FLAG} must be true or false, got {raw!r}")
    return raw == "true"
