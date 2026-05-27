"""Data types for the development inventory matrix.

`DevInventorySpec` is the value type `build_dev_inventory` consumes —
it carries everything `infinito administration inventory provision`
needs to materialise one development inventory folder. `PlanEntry` is
the per-round tuple `plan_dev_inventory_matrix` emits and the deploy
wrapper iterates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

# (round_index, inventory_dir, round_variants, include, purge_set) — include is the round's variant-closure (what to deploy); purge_set is the union over all rounds (what the inter-round wipe clears).
PlanEntry = tuple[int, str, dict[str, int], tuple[str, ...], tuple[str, ...]]


@dataclass(frozen=True)
class DevInventorySpec:
    """Everything `infinito administration inventory provision` needs to
    materialise one development inventory folder.

    `extra_vars` wins over the implicit `STORAGE_CONSTRAINED` / `RUNTIME`
    overrides so callers (and tests) keep the documented "user-provided
    vars always win" behaviour without re-implementing the merge.

    `active_variants` is the per-app variant index for the round this
    folder represents. Apps absent from the mapping (or with an out-of-
    range index) fall back to variant 0. The resolved variant payload
    for every app in `include` is baked into the inventory as an
    `applications.<app>` override, so the deploy stage no longer needs
    a runtime variant selector — the inventory itself is variant-resolved.
    """

    inventory_dir: str
    include: tuple[str, ...]
    storage_constrained: bool
    runtime: str
    extra_vars: Mapping[str, Any] | None = None
    services_disabled: str = ""
    active_variants: Mapping[str, int] | None = None

    def __post_init__(self) -> None:
        if not self.include:
            raise ValueError("DevInventorySpec.include must not be empty")
        if not isinstance(self.include, tuple):
            object.__setattr__(self, "include", tuple(self.include))

    def overrides(self) -> dict[str, Any]:
        merged: dict[str, Any] = {
            "STORAGE_CONSTRAINED": bool(self.storage_constrained),
            "RUNTIME": self.runtime,
        }
        if self.extra_vars:
            merged.update(self.extra_vars)
        return merged

    def variant_selectors(self) -> dict[str, int]:
        return dict(self.active_variants or {})

    def inventory_root(self) -> str:
        return str(self.inventory_dir).rstrip("/")
