from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.design.cosmos import DESIGN_PROVIDER, SERVICE_KEY
from utils.design.cosmos import cosmos_provider as _cosmos_provider
from utils.roles.applications.services.registry import (
    build_service_registry_from_applications,
    build_service_registry_from_roles_dir,
    is_explicit_truth,
    ordered_primary_service_entries,
)
from utils.roles.applications.services.resolver import ServicesResolver
from utils.roles.custom import is_custom
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

PROVIDER = "web-app-cst-cosmos"
APP = "web-svc-html"


def cosmos_provider(apps, application_id):
    return _cosmos_provider(
        apps, application_id, build_service_registry_from_applications(apps)
    )


def applications(design=True, app=None, provider=True):
    """
    Args:
        design: the ``services.cosmos.enabled`` value of the design role, or
            None when the design role does not declare the service.
        app: the ``services.cosmos.enabled`` value of the designed role, or
            None when it does not declare the service.
        provider: whether the cosmos role is pulled.

    Returns:
        An applications map with the design role, the designed role and,
        when pulled, the cosmos role.
    """
    apps = {
        DESIGN_PROVIDER: {"services": {}},
        APP: {"services": {}},
    }
    if design is not None:
        apps[DESIGN_PROVIDER]["services"]["cosmos"] = {
            "enabled": design,
            "shared": True,
        }
    if app is not None:
        apps[APP]["services"]["cosmos"] = {"enabled": app}
    if provider:
        apps[PROVIDER] = {"services": {"cosmos": {"enabled": True, "shared": True}}}
    return apps


class TestTheDesignRoleSwitchesCosmosOnForEveryDesignedRole(unittest.TestCase):
    def test_a_silent_role_gets_the_provider(self) -> None:
        self.assertEqual(cosmos_provider(applications(), APP), PROVIDER)

    def test_a_role_that_enables_it_gets_the_provider(self) -> None:
        self.assertEqual(cosmos_provider(applications(app=True), APP), PROVIDER)


class TestCosmosStaysOff(unittest.TestCase):
    def test_without_a_pulled_provider(self) -> None:
        self.assertEqual(cosmos_provider(applications(provider=False), APP), "")

    def test_while_the_design_role_does_not_declare_it(self) -> None:
        self.assertEqual(cosmos_provider(applications(design=None), APP), "")

    def test_while_the_design_role_disables_it(self) -> None:
        self.assertEqual(cosmos_provider(applications(design=False), APP), "")

    def test_for_a_role_that_forbids_it(self) -> None:
        for forbidden in (False, "false", "False", "no", "off", "0"):
            with self.subTest(enabled=forbidden):
                self.assertEqual(cosmos_provider(applications(app=forbidden), APP), "")


def designed_roles() -> list[str]:
    """
    Returns:
        Every in-tree role whose ``design`` service is enabled and shared on
        some node shape.
    """
    designed = []
    for path in sorted((PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_META_SERVICES}")):
        role = path.parent.parent.name
        entry = (load_yaml_any(str(path), default_if_missing={}) or {}).get("design")
        if (
            not is_custom(role)
            and role != DESIGN_PROVIDER
            and isinstance(entry, dict)
            and is_explicit_truth(entry.get("enabled"))
            and is_explicit_truth(entry.get("shared"))
        ):
            designed.append(role)
    return designed


def checkout(roles: Path, pulled: bool) -> None:
    """
    Args:
        roles: the empty roles directory to fill with every in-tree role.
        pulled: whether the cosmos provider role is placed beside them.
    """
    for path in sorted((PROJECT_ROOT / "roles").iterdir()):
        if path.is_dir() and not is_custom(path.name):
            (roles / path.name).symlink_to(path, target_is_directory=True)
    if pulled:
        (roles / PROVIDER / "meta").mkdir(parents=True)
        (roles / PROVIDER / "vars").mkdir()
        (roles / PROVIDER / ROLE_FILE_VARS_MAIN).write_text(
            f"application_id: {PROVIDER}\n", encoding="utf-8"
        )
        (roles / PROVIDER / ROLE_FILE_META_SERVICES).write_text(
            f"{SERVICE_KEY}:\n  enabled: true\n  shared: true\n", encoding="utf-8"
        )


class TestTheServiceResolverDeploysThePulledProviderWithEveryDesignedRole(
    unittest.TestCase
):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.roles = Path(self._tmp.name) / "roles"
        self.roles.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _ordered(self) -> dict[str, str]:
        entries = ordered_primary_service_entries(
            build_service_registry_from_roles_dir(self.roles), self.roles
        )
        return {entry["id"]: entry["role"] for entry in entries}

    def test_a_checkout_with_the_pulled_role_loads_it_for_every_designed_role(
        self,
    ) -> None:
        checkout(self.roles, pulled=True)
        self.assertEqual(self._ordered().get(SERVICE_KEY), PROVIDER)
        resolver = ServicesResolver(self.roles)
        roles = designed_roles()
        self.assertGreater(len(roles), 80)
        for role in roles:
            with self.subTest(role=role):
                self.assertIn(PROVIDER, resolver.resolve_transitively(role))

    def test_a_checkout_without_the_pulled_role_loads_nothing_for_the_key(
        self,
    ) -> None:
        checkout(self.roles, pulled=False)
        self.assertNotIn(SERVICE_KEY, self._ordered())
        resolver = ServicesResolver(self.roles)
        for role in designed_roles():
            with self.subTest(role=role):
                self.assertIn(DESIGN_PROVIDER, resolver.resolve_transitively(role))


if __name__ == "__main__":
    unittest.main()
