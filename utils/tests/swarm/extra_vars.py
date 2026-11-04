from __future__ import annotations

import json
import os

from utils.cache.base import _deep_merge


def with_extra_vars(overrides: dict) -> dict:
    """Lay INFINITO_INVENTORY_EXTRA_VARS over a round's inventory overrides.

    Args:
        overrides: the round's overrides (`applications`, `users`, ...).

    Returns:
        The overrides unchanged when the variable is unset or empty, otherwise
        the JSON object merged in recursively, the variable winning per leaf.
    """
    raw = os.environ.get("INFINITO_INVENTORY_EXTRA_VARS")
    if not raw:
        return overrides
    extra = json.loads(raw)
    if not isinstance(extra, dict):
        raise SystemExit(
            "swarm-matrix: INFINITO_INVENTORY_EXTRA_VARS must be a JSON object"
        )
    return _deep_merge(overrides, extra)
