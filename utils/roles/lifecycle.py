"""The CI-tested lifecycle envelope, read from ``default.env`` (the SPOT)."""

from __future__ import annotations

from utils.cache.files import PROJECT_ROOT
from utils.env.parser import parse_static_env


def tested_lifecycles() -> frozenset[str]:
    """Lifecycle stages the CI test-deploy discovery exercises.

    Reads the ``INFINITO_LIFECYCLES`` value from ``default.env`` so the
    envelope has a single source of truth instead of being duplicated as a
    hardcoded set at every consumer.
    """
    raw = parse_static_env(PROJECT_ROOT / "default.env")["INFINITO_LIFECYCLES"]
    return frozenset(raw.split())
