"""The `meta/addons/` map of one role, with its enable state resolved once.

Every consumer reads the same already-resolved view instead of re-deriving the
enable contract, which is why the normalisation happens at load time rather
than at each call site.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from .yaml import load_yaml as _load_yaml_cached

if TYPE_CHECKING:
    from pathlib import Path

META_ADDONS_DIR: str = "addons"


def normalize_addons(addons: Any) -> Any:
    """Normalise the `meta/addons/` map's enable state at load time.

    The enable contract (the unified addon contract's enable Decisions) is
    materialised here so every consumer reads one already-resolved view instead of
    re-deriving it: `required: true` defaults to enabled, an optional addon
    defaults to disabled, and an explicitly declared `enabled` value (literal
    or Jinja) is preserved verbatim. `required` itself is defaulted to
    `false` so downstream reads stay uniform.

    A new dict is returned per entry; the YAML cache's payload is never
    mutated. Malformed (non-mapping) payloads pass through untouched so the
    schema lint reports the offence with a precise message.
    """
    if not isinstance(addons, Mapping):
        return addons

    out: dict[str, Any] = {}
    for addon_id, spec in addons.items():
        if not isinstance(spec, Mapping):
            out[addon_id] = spec
            continue
        normalised = dict(spec)
        required = bool(normalised.get("required", False))
        normalised["required"] = required
        if "enabled" not in normalised:
            normalised["enabled"] = required
        out[addon_id] = normalised
    return out


def load_addons_dir(meta_dir: Path) -> dict[str, Any]:
    """Assemble the `addons` map from `meta/addons/<addon_id>.yml` files.

    Each file's root IS the addon spec; the filename stem is the addon id.
    The enable state is normalised (see `normalize_addons`). A missing or
    empty `meta/addons/` directory yields ``{}``.
    """
    addons_dir = meta_dir / META_ADDONS_DIR
    if not addons_dir.is_dir():
        return {}
    raw: dict[str, Any] = {}
    for path in sorted(addons_dir.glob("*.yml")):
        spec = _load_yaml_cached(path, default_if_missing={})
        if spec:
            raw[path.stem] = spec
    return normalize_addons(raw)
