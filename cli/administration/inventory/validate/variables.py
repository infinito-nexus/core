"""Inventory variable validation: every top-level key needs a reader in core.

A key counts as read when core declares it in ``group_vars`` or a role's
``defaults`` or ``vars``, tests it with ``is defined`` or ``| default(`` in its
YAML or Jinja, reads it by name from the variables in a plugin, is one of
the ``SYSTEM_EMAIL_<KEY>`` names the email lookup builds at run time, or is a
record the provisioning CLI keeps in host_vars and reads back on its next run.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: inventory-variable`` on, or directly above, the key's line.
"""

from __future__ import annotations

import re
from pathlib import Path

from cli.administration.inventory.provision.services_disabler import (
    DISABLED_SERVICES_RECORD,
)
from utils import PROJECT_ROOT
from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any

from .loaders import load_yaml_file

_RULE = "inventory-variable"
_NAME = r"([A-Za-z_][A-Za-z0-9_]*)"
_HOOK = re.compile(rf"\b{_NAME}\s+is\s+(?:not\s+)?defined|\b{_NAME}\s*\|\s*default\(")
_PLUGIN_READ = re.compile(
    rf"(?:variables|available_variables|hostvars\[[^\]]+\])\s*(?:\.get\(\s*|\[\s*)[\"']{_NAME}[\"']"
)
_EMAIL_KEYS = re.compile(r"RESOLUTION_ORDER = \(([^)]*)\)")


def _relative(path: str) -> tuple[str, ...]:
    return Path(path).relative_to(PROJECT_ROOT).parts


def declared_variables() -> set[str]:
    """Return every variable core declares in group_vars or a role's defaults and vars.

    Returns:
        The top-level keys of ``group_vars/**`` and ``roles/*/{defaults,vars}/**``.
    """
    names: set[str] = set()
    for path in iter_project_files(extensions=(".yml", ".yaml")):
        parts = _relative(path)
        if parts[0] == "group_vars" or (
            parts[0] == "roles" and len(parts) > 3 and parts[2] in ("defaults", "vars")
        ):
            data = load_yaml_any(path, default_if_missing=None)
            if isinstance(data, dict):
                names.update(data)
    return names


def read_variables() -> set[str]:
    """Return every variable core reads, declared or not.

    Returns:
        ``declared_variables()`` plus the names core guards with ``is defined``
        or ``| default(``, the names plugins read from the variables by name,
        the ``SYSTEM_EMAIL_<KEY>`` names and the provisioning records.
    """
    names = declared_variables() | {DISABLED_SERVICES_RECORD}
    for path in iter_project_files(
        extensions=(".yml", ".yaml", ".j2"), exclude_tests=True
    ):
        for match in _HOOK.findall(read_text(path)):
            names.update(name for name in match if name)
    for path in iter_project_files(extensions=(".py",), exclude_tests=True):
        if _relative(path)[0] in ("plugins", "utils", "roles", "filter_plugins"):
            names.update(_PLUGIN_READ.findall(read_text(path)))
    email = _EMAIL_KEYS.search(
        read_text(str(PROJECT_ROOT / "plugins" / "lookup" / "email.py"))
    )
    names.update(
        f"SYSTEM_EMAIL_{key.upper()}"
        for key in re.findall(r"[\"'](\w+)[\"']", email.group(1) if email else "")
    )
    return names


def validate_inventory_variables(
    inv_dir, known: set[str], moved: dict[str, str]
) -> list[str]:
    """Report top-level inventory variables the deploy never reads.

    Args:
        inv_dir: the inventory directory.
        known: the variables core reads, see ``read_variables()``.
        moved: flat name to the path its value moved to, see ``legacy_api_keys()``.

    Returns:
        One message per unread key of ``host_vars/**`` and ``group_vars/**``
        that carries no ``inventory-variable`` marker.
    """
    root = Path(inv_dir)
    errs: list[str] = []
    files = sorted(
        {*root.glob("host_vars/**/*.yml"), *root.glob("group_vars/**/*.yml")}
    )
    for path in files:
        data = load_yaml_file(path)
        if not isinstance(data, dict):
            continue
        lines = read_text(str(path)).splitlines()
        for key in data:
            name = str(key)
            if (name in known and name not in moved) or name.startswith("ansible_"):
                continue
            number = next(
                (n for n, line in enumerate(lines, 1) if line.startswith(f"{name}:")),
                0,
            )
            if number and is_suppressed_at(lines, number, _RULE):
                continue
            hint = (
                f"move its value to {moved[name]}"
                if name in moved
                else "no group_vars, role defaults or role vars declare it and no plugin reads it"
            )
            errs.append(f"{path}: '{name}' is not read by the deploy; {hint}")
    return errs
