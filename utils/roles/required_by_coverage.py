"""Static classifiers used by the `required_by` lint and verifier:
role invokability (per categories.yml), `required_by` presence in
`meta/services.yml`, and `# nocheck: <id>` opt-outs.
"""

from __future__ import annotations

import re
from pathlib import Path

from plugins.filter.invokable_paths import get_invokable_paths
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.categories import categories_file
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.roles.validation.invokable import _is_role_invokable

from . import PROJECT_ROOT


def _default_roles_dir(roles_dir: str | Path | None) -> Path:
    return Path(roles_dir) if roles_dir else (PROJECT_ROOT / "roles")


def role_is_invokable(role_id: str, roles_dir: str | Path | None = None) -> bool:
    """True when `role_id` sits at or below a category marked ``invokable: true``.

    Args:
        role_id: the role to classify.
        roles_dir: the roles directory whose sibling ``categories.yml`` decides.
    """
    if not role_id:
        return False
    spot = categories_file(_default_roles_dir(roles_dir).parent)
    return _is_role_invokable(role_id, [str(p) for p in get_invokable_paths(str(spot))])


def role_has_required_by(role_id: str, roles_dir: str | Path | None = None) -> bool:
    """True if any entity in `roles/<role_id>/meta/services.yml` declares
    non-empty `required_by` categories/roles, either flat or nested under a
    `compose:`/`swarm:` mode block."""
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
        blocks = (
            [rb[m] for m in ("compose", "swarm") if isinstance(rb.get(m), dict)]
            if ("compose" in rb or "swarm" in rb)
            else [rb]
        )
        if any(b.get("categories") or b.get("roles") for b in blocks):
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
