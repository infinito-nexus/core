"""SPOT for development inventory creation.

Anything that wants to materialise the development inventory MUST go
through :func:`build_dev_inventory` (single folder) or
:func:`build_dev_inventory_matrix` (one folder per matrix-deploy round).
Both flow through :class:`~.spec.DevInventorySpec` and own:

* the SPOT vars-file (``DEV_INVENTORY_VARS_FILE``),
* per-app variant baking (each role's ``meta/variants.yml`` is resolved
  at build time and emitted as ``applications.<app>`` overrides into
  the inventory's ``host_vars``, with variant 0 as the fallback for
  every role that is not a primary in the current matrix round),
* the vault password file.

The deploy wrapper consumes :func:`plan_dev_inventory_matrix` to know
which folder to deploy against in each round; the planner is a pure
function so wrapper and init step compute the same plan independently.

Internal layout (one module per responsibility):

* :mod:`.spec`            — :class:`~.spec.DevInventorySpec` + ``PlanEntry`` type
* :mod:`.payload`         — variant payload pick + ``--vars`` bake
* :mod:`.legacy_resolver` — ``CombinedResolver``-driven include resolution
* :mod:`.planner`         — :func:`plan_dev_inventory_matrix`
* :mod:`.builder`         — :func:`build_dev_inventory` + matrix orchestrator

The private helpers (``_resolve_round_include`` and friends) are
re-exported below because unit tests historically patch them under this
package path. New tests SHOULD patch the submodule path directly
(e.g. ``inventory.legacy_resolver._resolve_round_include``).

``DevInventorySpec`` is imported but deliberately absent from ``__all__``:
listing a re-exported class makes autodoc document it here as well as in
:mod:`.spec`, and sphinx then finds two targets for every annotation. Importing
it from this package keeps working either way.
"""

from __future__ import annotations

from .builder import build_dev_inventory, build_dev_inventory_matrix
from .legacy_resolver import (
    _build_services_overrides_for_round,
    _resolve_round_include,
    prune_orphans_after_disable,
)
from .payload import _bake_overrides, _resolve_variant_payloads
from .planner import filter_plan_to_variants, plan_dev_inventory_matrix
from .spec import DevInventorySpec, PlanEntry

__all__ = [
    "PlanEntry",
    "_bake_overrides",
    "_build_services_overrides_for_round",
    "_resolve_round_include",
    "_resolve_variant_payloads",
    "build_dev_inventory",
    "build_dev_inventory_matrix",
    "filter_plan_to_variants",
    "plan_dev_inventory_matrix",
    "prune_orphans_after_disable",
]
