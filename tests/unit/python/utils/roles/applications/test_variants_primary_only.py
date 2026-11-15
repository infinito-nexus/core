"""Unit tests for the primary-only hosts of `utils.roles.applications.variants`."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar
from unittest.mock import patch

from utils.roles.applications.services.registry import (
    resolve_service_dependency_roles_from_config,
)
from utils.roles.applications.variants import (
    PRIMARY_ONLY_SERVICE_KEYS,
    SEMAPHORE_SERVICE_KEY,
    primary_only,
    services_overrides_for_round,
)
from utils.roles.guide import GUIDE_SERVICE_KEY

SEMAPHORE = "web-app-semaphore"
LEAF = "web-app-leaf"
PINNER = "web-app-pinner"
GATE = "{{ 'web-app-semaphore' in group_names }}"

SEMAPHORE_SERVICES = """\
---
semaphore:
  bond: 1
  enabled: true
  shared: true
  control: false
  status: started
"""

CONSUMER_SERVICES = f"""\
---
own:
  image: own
semaphore:
  bond: 0.5
  enabled: "{GATE}"
  shared: "{GATE}"
  control: true
  status: started
"""

PINNER_VARIANTS = """\
---
- {}
- services:
    semaphore:
      enabled: true
      shared: true
"""

REGISTRY: dict[str, dict[str, str]] = {SEMAPHORE_SERVICE_KEY: {"role": SEMAPHORE}}


class TestPrimaryOnly(unittest.TestCase):
    def test_both_hosts_are_primary_only(self) -> None:
        self.assertEqual(
            (GUIDE_SERVICE_KEY, SEMAPHORE_SERVICE_KEY), PRIMARY_ONLY_SERVICE_KEYS
        )

    def test_a_partner_has_every_host_off_and_keeps_its_other_keys(self) -> None:
        services = {
            "docs": {"bond": 0.5, "enabled": True, "shared": True},
            "semaphore": {"enabled": True, "shared": True, "control": True},
            "own": {"enabled": True},
        }
        self.assertEqual(
            {
                "docs": {"bond": 0.5, "enabled": False, "shared": False},
                "semaphore": {"enabled": False, "shared": False, "control": True},
                "own": {"enabled": True},
            },
            primary_only(services, primary=False),
        )

    def test_a_primary_keeps_a_literal_true(self) -> None:
        services = {"semaphore": {"enabled": True, "shared": True}}
        self.assertEqual(services, primary_only(services, primary=True))

    def test_a_primary_loses_the_group_gate(self) -> None:
        services = {"semaphore": {"enabled": GATE, "shared": GATE}}
        self.assertEqual(
            {"semaphore": {"enabled": False, "shared": False}},
            primary_only(services, primary=True),
        )

    def test_a_role_without_the_hosts_is_left_as_it_is(self) -> None:
        self.assertEqual(
            {"own": {"enabled": True}},
            primary_only({"own": {"enabled": True}}, primary=False),
        )


class TestSemaphoreRoundComposition(unittest.TestCase):
    _tmp: ClassVar[TemporaryDirectory]
    roles_dir: ClassVar[str]

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = TemporaryDirectory()
        roles = Path(cls._tmp.name) / "roles"
        cls._write(roles, SEMAPHORE, "services.yml", SEMAPHORE_SERVICES)
        cls._write(roles, LEAF, "services.yml", CONSUMER_SERVICES)
        cls._write(roles, PINNER, "services.yml", CONSUMER_SERVICES)
        cls._write(roles, PINNER, "variants.yml", PINNER_VARIANTS)
        cls.roles_dir = str(roles)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def setUp(self) -> None:
        self.enterContext(
            patch(
                "utils.roles.applications.variants._resolve_round_include",
                side_effect=lambda primary_apps, services_overrides: primary_apps,
            )
        )

    @staticmethod
    def _write(roles: Path, role: str, name: str, body: str) -> None:
        path = roles / role / "meta" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)

    def _pulled(self, round_index: int, primaries: dict[str, int]) -> set[str]:
        overrides = services_overrides_for_round(
            roles_dir=self.roles_dir,
            round_index=round_index,
            primary_app_variants=primaries,
        )
        return {
            provider
            for role, services in overrides.items()
            for provider in resolve_service_dependency_roles_from_config(
                {"services": services}, REGISTRY
            )
            if provider != role
        }

    def test_a_leaf_round_pulls_no_semaphore(self) -> None:
        self.assertNotIn(SEMAPHORE, self._pulled(0, {LEAF: 0}))

    def test_a_partner_declaring_it_does_not_pull_it_in(self) -> None:
        self.assertNotIn(SEMAPHORE, self._pulled(1, {LEAF: 0}))

    def test_the_group_gate_of_a_primary_does_not_pull_it_in(self) -> None:
        self.assertNotIn(SEMAPHORE, self._pulled(0, {PINNER: 0}))

    def test_a_primary_variant_declaring_it_pulls_it_in(self) -> None:
        self.assertIn(SEMAPHORE, self._pulled(1, {PINNER: 1}))

    def test_the_semaphore_round_keeps_its_own_container(self) -> None:
        overrides = services_overrides_for_round(
            roles_dir=self.roles_dir,
            round_index=0,
            primary_app_variants={SEMAPHORE: 0},
        )
        self.assertIs(True, overrides[SEMAPHORE][SEMAPHORE_SERVICE_KEY]["enabled"])
        self.assertIs(False, overrides[LEAF][SEMAPHORE_SERVICE_KEY]["enabled"])


if __name__ == "__main__":
    unittest.main()
