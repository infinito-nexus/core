"""Host-group validation: inventory `all.children` keys vs application IDs."""

from __future__ import annotations

from pathlib import Path

from .loaders import load_yaml_file


def validate_host_keys(app_ids, inv_dir) -> list[str]:
    errs: list[str] = []
    p = Path(inv_dir)
    for f in p.glob("*.yml"):
        data = load_yaml_file(f)
        if not isinstance(data, dict):
            continue
        all_node = data.get("all", {})
        children = all_node.get("children")
        if not isinstance(children, dict):
            continue
        errs.extend(
            f"{f}: Invalid group '{grp}' (not in application_ids)"
            for grp in children
            if grp not in app_ids
        )
    return errs
