from __future__ import annotations

from typing import Any


def parse_roles_list(raw_roles: list[str] | None) -> set[str] | None:
    """
    Parse a list of IDs supplied on the CLI. Supports:
      --include web-app-nextcloud web-app-mastodon
      --include web-app-nextcloud,web-app-mastodon
    Same logic is reused for --exclude and --roles.
    """
    if not raw_roles:
        return None
    result: set[str] = set()
    for raw_token in raw_roles:
        token = raw_token.strip()
        if not token:
            continue
        for raw_part in token.split(","):
            part = raw_part.strip()
            if part:
                result.add(part)
    return result


def _filter_inventory_children(
    inv_data: dict[str, Any], keep_predicate
) -> dict[str, Any]:
    all_block = inv_data.get("all", {}) or {}
    children = (
        (all_block.get("children", {}) or {}) if isinstance(all_block, dict) else {}
    )

    filtered: dict[str, Any] = {
        group_name: group_data
        for group_name, group_data in children.items()
        if keep_predicate(group_name, group_data)
    }

    new_all = dict(all_block)
    new_all["children"] = filtered
    return {"all": new_all}


def filter_dynamic_inventory(
    dyn_inv: dict[str, Any],
    include_filter: set[str] | None,
    exclude_filter: set[str] | None,
    legacy_roles_filter: set[str] | None,
) -> dict[str, Any]:
    """
    Apply include/exclude/legacy role filters in the same order as before:
      include -> exclude -> legacy roles
    """
    if include_filter:
        print(
            f"[INFO] Including only application_ids: {', '.join(sorted(include_filter))}"
        )
        return _filter_inventory_children(
            dyn_inv, lambda name, _d: name in include_filter
        )

    if exclude_filter:
        print(f"[INFO] Ignoring application_ids: {', '.join(sorted(exclude_filter))}")
        return _filter_inventory_children(
            dyn_inv, lambda name, _d: name not in exclude_filter
        )

    if legacy_roles_filter:
        print(
            f"[INFO] Filtering inventory to roles (legacy): {', '.join(sorted(legacy_roles_filter))}"
        )
        return _filter_inventory_children(
            dyn_inv, lambda name, _d: name in legacy_roles_filter
        )

    return dyn_inv
