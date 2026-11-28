from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.cache.yaml import load_yaml_any
from utils.roles.deploy import role_deploy_modes
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

BUNDLES = PROJECT_ROOT / "inventories" / "bundles"
ROLES = PROJECT_ROOT / "roles"


def bundle_roles(inventory: Path) -> list[str]:
    """Args:
        inventory: the bundle's ``inventory.yml``.

    Returns:
        The ``all.children`` keys, empty when the inventory declares none.
    """
    data = load_yaml_any(str(inventory), default_if_missing={})
    if not isinstance(data, dict):
        return []
    return sorted(((data.get("all") or {}).get("children")) or {})


def undeployable(roles_dir: Path, bundles_dir: Path) -> list[str]:
    """Args:
        roles_dir: the directory holding ``<role>/meta/services.yml``.
        bundles_dir: the directory holding ``<kind>/<bundle>/inventory.yml``.

    Returns:
        One ``<inventory>: <role>`` finding per role whose
        ``modes.<mode>.enabled`` is false for every mode it declares.
    """
    found: list[str] = []
    for inventory in sorted(bundles_dir.glob("*/*/inventory.yml")):
        for role in bundle_roles(inventory):
            role_dir = roles_dir / role
            if not (role_dir / ROLE_FILE_META_SERVICES).is_file():
                continue
            modes = role_deploy_modes(role_dir, role)
            if modes and not any(modes.values()):
                found.append(f"{inventory.relative_to(bundles_dir)}: {role}")
    return found


class TestBundleRolesDeployable(unittest.TestCase):
    def test_no_bundle_deploys_a_role_without_a_mode(self):
        self.assertEqual(undeployable(ROLES, BUNDLES), [])

    def test_red_bundle_with_a_modeless_role_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            meta = root / "roles" / "web-svc-probe" / "meta"
            meta.mkdir(parents=True)
            (root / "roles" / "web-svc-probe" / ROLE_FILE_META_SERVICES).write_text(
                "probe:\n  modes:\n    compose:\n      enabled: false\n"
                "    swarm:\n      enabled: false\n",
                encoding="utf-8",
            )
            bundle = root / "bundles" / "servers" / "probe"
            bundle.mkdir(parents=True)
            (bundle / "inventory.yml").write_text(
                "all:\n  children:\n    web-svc-probe:\n      hosts:\n        server:\n",
                encoding="utf-8",
            )
            self.assertEqual(
                undeployable(root / "roles", root / "bundles"),
                ["servers/probe/inventory.yml: web-svc-probe"],
            )


if __name__ == "__main__":
    unittest.main()
