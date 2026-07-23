"""Deploy-stage lookup SPOT.

``roles/categories.yml`` declares the ordered ``stages`` (constructor ->
workstation -> server -> destructor, matching ``tasks/stages/0*.yml``) and a
``stage`` per top-level category. This module resolves a role to its stage and
exposes the canonical stage order, so both the CLI (``cli.meta.roles.order``)
and the ``stage_order`` / ``role_stage`` lookups read one source of truth.
"""

from __future__ import annotations

from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml
from utils.roles.applications.services.registry import run_after_topological_order

DEFAULT_STAGE = "server"


def _categories_file() -> str | None:
    for loc in (
        Path.cwd() / "roles" / "categories.yml",
        PROJECT_ROOT / "roles" / "categories.yml",
        Path("roles/categories.yml"),
    ):
        if Path(loc).exists():
            return str(loc)
    return None


def _doc() -> dict:
    f = _categories_file()
    return load_yaml(f) if f else {}


_META_DICT_KEYS = frozenset({"modes"})


def _category_nodes(tree: dict, prefix: str = ""):
    """Yield ``(dash-joined-prefix, node)`` for every category node. Scalar
    meta keys (title/stage/invokable) and list keys (run_after) are skipped
    because only sub-category values are dicts; dict-valued meta keys are
    excluded via _META_DICT_KEYS."""
    for key, node in tree.items():
        if not isinstance(node, dict) or key in _META_DICT_KEYS:
            continue
        current = f"{prefix}-{key}" if prefix else key
        yield current, node
        yield from _category_nodes(node, current)


def stage_order() -> list[str]:
    """Canonical deploy-stage order."""
    return list(_doc().get("stages") or [])


def _longest_prefix_match(role: str, prefixes) -> str | None:
    role_lc = role.lower()
    best = None
    for prefix in prefixes:
        p = prefix.lower()
        if (role_lc == p or role_lc.startswith(p + "-")) and (
            best is None or len(prefix) > len(best)
        ):
            best = prefix
    return best


def role_stage(role: str) -> str:
    """The stage a role is invoked in (deepest matching category wins)."""
    stage_map = {
        p: n["stage"]
        for p, n in _category_nodes(_doc().get("roles", {}))
        if "stage" in n
    }
    match = _longest_prefix_match(role, stage_map)
    return stage_map[match] if match else DEFAULT_STAGE


def role_modes_defaults(role: str) -> dict:
    """Mode-enabled defaults a role's services must declare, from the deepest
    categories.yml category carrying a ``modes`` mapping (parents apply when
    no deeper category declares one). Empty when no category declares modes."""
    modes_map = {
        p: n["modes"]
        for p, n in _category_nodes(_doc().get("roles", {}))
        if isinstance(n.get("modes"), dict)
    }
    match = _longest_prefix_match(role, modes_map)
    return dict(modes_map[match]) if match else {}


def _category_order() -> dict[str, int]:
    nodes = [p for p, _ in _category_nodes(_doc().get("roles", {}))]
    run_after = {
        p: list(n.get("run_after") or [])
        for p, n in _category_nodes(_doc().get("roles", {}))
    }
    ordered = run_after_topological_order(
        nodes, lambda x: run_after.get(x, []), lambda x: x
    )
    return {p: i for i, p in enumerate(ordered)}


def role_sort_key(role: str) -> tuple:
    """Sort key placing a role by (stage, category run_after, name). Used as
    the run_after tiebreak so ready roles fall out in call order."""
    order = stage_order()
    stage = role_stage(role)
    stage_idx = order.index(stage) if stage in order else len(order)
    cat_order = _category_order()
    cat_rank = cat_order.get(_longest_prefix_match(role, cat_order), len(cat_order))
    return (stage_idx, cat_rank, role)


def _group_names() -> list[str]:
    groups_dir = PROJECT_ROOT / "tasks" / "groups"
    if not groups_dir.is_dir():
        return []
    return [p.name.removesuffix("-roles.yml") for p in groups_dir.glob("*-roles.yml")]


def _bootstrap_prefixes() -> set[str]:
    """Categories flagged ``bootstrap: true`` — included via dedicated bootstrap
    steps in the play, not the generic stage group-loop."""
    return {
        p for p, n in _category_nodes(_doc().get("roles", {})) if n.get("bootstrap")
    }


def stage_groups(stage: str) -> list[str]:
    """Ordered role-group names (``tasks/groups/<g>-roles.yml``) that belong to
    ``stage``, in intra-stage call order (category run_after, then name). The
    SPOT the stage plays consume so group membership follows categories.yml.
    Bootstrap-flagged categories are excluded (they run via explicit steps)."""
    cat_order = _category_order()
    bootstrap = _bootstrap_prefixes()
    groups = [
        g
        for g in _group_names()
        if role_stage(g) == stage and _longest_prefix_match(g, bootstrap) is None
    ]
    return sorted(
        groups, key=lambda g: (cat_order.get(_longest_prefix_match(g, cat_order), 0), g)
    )
