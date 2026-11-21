"""L24: the agents bundle inventory deploys the whole agent platform, and the
deliberately vulnerable fixture app appears in no other inventory, so its seeded
findings never reach a real deployment."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

INVENTORIES = PROJECT_ROOT / "inventories"
BUNDLE = INVENTORIES / "bundles" / "servers" / "agents" / "inventory.yml"
FIXTURE_ROLE = "web-app-agent-fixture"
REQUIRED = {
    "svc-ai-agent-broker",
    "svc-ai-agent-orchestrator",
    "svc-ai-agent-provisioner",
    "web-app-workspace",
    "web-app-agent-fixture",
    "web-app-gitea",
    "web-app-matrix",
    "web-app-openproject",
    "web-app-nextcloud",
    "web-app-zammad",
    "web-app-weblate",
    "web-app-keycloak",
    "svc-db-openldap",
    "svc-db-postgres",
    "svc-ai-ollama",
    "svc-ai-litellm",
}


def inventory_children(inventory_file: Path) -> set[str]:
    """Return the child group names of an inventory, empty when it has none."""
    data = (
        load_yaml_any(str(inventory_file), default_if_missing={})
        if inventory_file.is_file()
        else None
    )
    if not isinstance(data, dict):
        return set()
    return set(((data.get("all") or {}).get("children")) or {})


def missing_roles(bundle: Path) -> list[str]:
    """Return the required agent-platform roles the bundle does not deploy."""
    return sorted(REQUIRED - inventory_children(bundle))


def stray_fixture(inventories: Path) -> list[str]:
    """Return every inventory other than the agents bundle that deploys the fixture."""
    out: list[str] = []
    for path in sorted(inventories.rglob("*.yml")):  # nocheck: project-walk
        if path.resolve() == BUNDLE.resolve():
            continue
        if FIXTURE_ROLE in inventory_children(path):
            out.append(str(path.relative_to(PROJECT_ROOT)))
    return out


class TestL24(unittest.TestCase):
    def test_bundle_holds_every_named_role(self):
        self.assertEqual(missing_roles(BUNDLE), [])

    def test_fixture_is_bundle_exclusive(self):
        self.assertEqual(stray_fixture(INVENTORIES), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            inv = Path(tmp) / "inventory.yml"
            inv.write_text(
                "all:\n  children:\n    web-app-gitea:\n      hosts:\n        server:\n",
                encoding="utf-8",
            )
            self.assertNotEqual(missing_roles(inv), [])


if __name__ == "__main__":
    unittest.main()
