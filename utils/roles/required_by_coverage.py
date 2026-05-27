"""Static classifiers used by the `required_by` lint and verifier:
role invokability (per categories.yml), `required_by` presence in
`meta/services.yml`, and `# nocheck: <id>` opt-outs.
"""

from __future__ import annotations

import re
from pathlib import Path

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT


def _default_roles_dir(roles_dir: str | Path | None) -> Path:
    return Path(roles_dir) if roles_dir else (PROJECT_ROOT / "roles")


def role_is_invokable(role_id: str, roles_dir: str | Path | None = None) -> bool:
    """True when any node along `role_id`'s category path has `invokable: true`."""
    if not role_id:
        return False
    base = _default_roles_dir(roles_dir)
    tree_doc = load_yaml_any(str(base / "categories.yml"), default_if_missing={})
    tree = tree_doc.get("roles") or {} if isinstance(tree_doc, dict) else {}

    node = tree
    for seg in str(role_id).split("-"):
        if not seg or not isinstance(node, dict) or seg not in node:
            break
        node = node[seg]
        if isinstance(node, dict) and node.get("invokable") is True:
            return True
    return False


def role_has_required_by(role_id: str, roles_dir: str | Path | None = None) -> bool:
    """True if any entity in `roles/<role_id>/meta/services.yml` declares
    `required_by.categories` or `required_by.roles` (non-empty)."""
    if not role_id:
        return False
    base = _default_roles_dir(roles_dir)
    services_yml = base / str(role_id) / ROLE_FILE_META_SERVICES
    if not services_yml.is_file():
        return False
    data = load_yaml_any(str(services_yml), default_if_missing={})
    if not isinstance(data, dict):
        return False
    for entry in data.values():
        if not isinstance(entry, dict):
            continue
        rb = entry.get("required_by")
        if not isinstance(rb, dict):
            continue
        if rb.get("categories") or rb.get("roles"):
            return True
    return False


def role_has_nocheck(
    role_id: str,
    check_id: str,
    roles_dir: str | Path | None = None,
) -> bool:
    """True if `roles/<role_id>/meta/services.yml` contains
    `# nocheck: <check_id>` (whole-word match)."""
    if not role_id or not check_id:
        return False
    base = _default_roles_dir(roles_dir)
    services_yml = base / str(role_id) / ROLE_FILE_META_SERVICES
    if not services_yml.is_file():
        return False
    pattern = re.compile(rf"#\s*nocheck:\s*{re.escape(check_id)}(?!\S)")
    try:
        return bool(pattern.search(read_text(str(services_yml))))
    except OSError:
        return False
