"""Extract literal ``default:`` credential values from a ``meta/schema.yml``
``credentials:`` tree.

Kept in its own module so ``utils.cache.applications`` stays under the
repo's per-file line cap. Strictly ansible-free (stdlib only) so the
runner-host CLI path keeps importing it without ansible installed.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_LEAF_MARKERS: tuple[str, ...] = ("default", "algorithm", "validation", "description")


def extract_default_credentials(creds_node: Any) -> dict[str, Any]:
    """Return the subset of a ``credentials:`` tree's leaves that carry a
    literal ``default:`` Jinja string.

    The shape mirrors the schema tree: nested keys stay nested. The literal
    string is preserved verbatim, with no rendering and no validation. Leaves
    WITHOUT ``default:`` are intentionally absent so the inventory's
    apply_schema-generated values win the merge.
    """
    if not isinstance(creds_node, Mapping):
        return {}

    if any(marker in creds_node for marker in _LEAF_MARKERS):
        return {}

    out: dict[str, Any] = {}
    for key, value in creds_node.items():
        if not isinstance(value, Mapping):
            continue
        if any(marker in value for marker in _LEAF_MARKERS):
            if "default" in value:
                out[key] = value["default"]
        else:
            nested = extract_default_credentials(value)
            if nested:
                out[key] = nested
    return out
