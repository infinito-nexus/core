"""Guard: only ``web-*`` roles may integrate the dashboard.

A role "integrates" the dashboard when its ``meta/services.yml`` (or
any entry in ``meta/variants.yml``) declares a ``dashboard:`` block
whose ``enabled`` or ``shared`` flag is truthy according to the
canonical helper :func:`utils.roles.applications.services.registry.is_explicit_truth`.

Truthy means either the literal Python ``True`` *or* the dynamic Jinja
form ``"{{ '<role>' in group_names }}"``. Both produce a runtime tile
in the dashboard grid, so both are forbidden for non-``web-*`` roles.

Why
---

The dashboard is the user-facing tile grid. Only web-facing surfaces
belong in it. A system role (``sys-*``), desktop role (``desk-*``),
service role (``svc-*``), or driver role (``drv-*``) embedding the
dashboard would spam the tile grid with non-clickable infrastructure
entries.

A non-``web-*`` role MAY still ship a ``dashboard:`` block with
*explicitly disabled* flags (``enabled: false`` / ``shared: false``)
- that's a static "we know this service exists in the registry but
this role does not contribute a tile" declaration and is fine.
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING, Any

from utils.cache.yaml import load_yaml_any
from utils.roles.applications.services.registry import is_explicit_truth
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_VARIANTS

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"
DASHBOARD_KEY = "dashboard"


def _load_yaml(path: Path) -> Any:
    if not path.is_file():
        return None
    return load_yaml_any(str(path), default_if_missing=None)


def _dashboard_block_violates(block: Any) -> bool:
    """Return True iff the ``dashboard:`` mapping has a truthy
    ``enabled`` or ``shared`` flag."""
    if not isinstance(block, dict):
        return False
    return is_explicit_truth(block.get("enabled")) or is_explicit_truth(
        block.get("shared")
    )


def _find_services_violation(role_dir: Path) -> str | None:
    services_yaml = _load_yaml(role_dir / ROLE_FILE_META_SERVICES)
    if not isinstance(services_yaml, dict):
        return None
    if _dashboard_block_violates(services_yaml.get(DASHBOARD_KEY)):
        return f"{role_dir.name}: meta/services.yml declares `dashboard:` with a truthy enabled/shared flag"
    return None


def _find_variants_violations(role_dir: Path) -> list[str]:
    variants_yaml = _load_yaml(role_dir / ROLE_FILE_META_VARIANTS)
    if not isinstance(variants_yaml, list):
        return []
    offenders: list[str] = []
    for index, entry in enumerate(variants_yaml):
        if not isinstance(entry, dict):
            continue
        services_override = entry.get("services")
        if not isinstance(services_override, dict):
            continue
        if _dashboard_block_violates(services_override.get(DASHBOARD_KEY)):
            offenders.append(
                f"{role_dir.name}: meta/variants.yml[{index}].services.dashboard "
                f"has a truthy enabled/shared flag"
            )
    return offenders


class TestDashboardIntegrationScope(unittest.TestCase):
    def test_only_web_roles_integrate_dashboard(self) -> None:
        offenders: list[str] = []
        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            if role_dir.name.startswith("web-"):
                continue
            services_violation = _find_services_violation(role_dir)
            if services_violation is not None:
                offenders.append(services_violation)
            offenders.extend(_find_variants_violations(role_dir))

        if offenders:
            self.fail(
                "Non-web roles MUST NOT integrate the dashboard via a "
                "truthy `enabled`/`shared` flag (literal `true` or the "
                "`'<role>' in group_names` Jinja form). The dashboard tile "
                "grid is reserved for web-facing surfaces. "
                "Either drop the `dashboard:` block, or set both flags to "
                "`false` if the registry declaration is intentional:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
