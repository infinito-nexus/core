from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.design.cosmos import (
    DESIGN_PROVIDER,
    FLAVOR_COLORS,
    FLAVOR_FULL,
    FLAVOR_KEY,
    FLAVORS,
    SERVICE_KEY,
)
from utils.design.cosmos import cosmos_flavor as _cosmos_flavor
from utils.design.cosmos import cosmos_provider as _cosmos_provider
from utils.roles.applications.services.registry import (
    build_service_registry_from_applications,
    build_service_registry_from_roles_dir,
    is_explicit_truth,
    load_applications_from_roles_dir,
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


def cosmos_flavor(apps, application_id):
    return _cosmos_flavor(
        apps, application_id, build_service_registry_from_applications(apps)
    )


def flavored(apps, design=None, app=None):
    """
    Args:
        apps: an applications map :func:`applications` built.
        design: the ``services.cosmos.flavor`` of the design role, or None to
            leave it unset.
        app: the ``services.cosmos.flavor`` of the designed role, or None to
            leave it unset.

    Returns:
        ``apps`` with those flavors set.
    """
    for role, flavor in ((DESIGN_PROVIDER, design), (APP, app)):
        if flavor is not None:
            apps[role]["services"].setdefault(SERVICE_KEY, {})[FLAVOR_KEY] = flavor
    return apps


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


class TestTheFlavorComesFromTheDesignRoleUnlessTheRoleSetsOne(unittest.TestCase):
    def test_a_silent_role_takes_the_flavor_of_the_design_role(self) -> None:
        for flavor in FLAVORS:
            with self.subTest(design=flavor):
                apps = flavored(applications(), design=flavor)
                self.assertEqual(cosmos_flavor(apps, APP), flavor)

    def test_the_flavor_of_the_role_wins_over_the_design_role(self) -> None:
        for own in FLAVORS:
            for default in FLAVORS:
                with self.subTest(app=own, design=default):
                    apps = flavored(applications(), design=default, app=own)
                    self.assertEqual(cosmos_flavor(apps, APP), own)

    def test_an_empty_flavor_of_the_role_counts_as_unset(self) -> None:
        for empty in ("", "  "):
            with self.subTest(app=empty):
                apps = flavored(applications(), design=FLAVOR_COLORS, app=empty)
                self.assertEqual(cosmos_flavor(apps, APP), FLAVOR_COLORS)


class TestTheFlavorIsEmptyWithoutAnActiveProvider(unittest.TestCase):
    def test_while_no_provider_is_active(self) -> None:
        for label, apps in (
            ("not pulled", applications(provider=False)),
            ("design role off", applications(design=False)),
            ("role forbids it", applications(app=False)),
        ):
            with self.subTest(case=label):
                self.assertEqual(cosmos_provider(apps, APP), "")
                flavored(apps, design=FLAVOR_FULL, app=FLAVOR_COLORS)
                self.assertEqual(cosmos_flavor(apps, APP), "")

    def test_the_same_flavors_resolve_once_the_provider_is_active(self) -> None:
        apps = flavored(applications(), design=FLAVOR_FULL, app=FLAVOR_COLORS)
        self.assertEqual(cosmos_flavor(apps, APP), FLAVOR_COLORS)


class TestAnInvalidFlavorFailsLoudly(unittest.TestCase):
    INVALID = ("off", "Full", "sky", True, 1, None)

    def test_an_invalid_flavor_of_the_role_names_the_role_and_the_key(self) -> None:
        for invalid in self.INVALID:
            with self.subTest(app=invalid):
                apps = flavored(applications(), design=FLAVOR_FULL)
                apps[APP]["services"][SERVICE_KEY] = {FLAVOR_KEY: invalid}
                with self.assertRaisesRegex(
                    ValueError, rf"^{APP}: services\.{SERVICE_KEY}\.{FLAVOR_KEY} "
                ):
                    cosmos_flavor(apps, APP)

    def test_an_invalid_flavor_of_the_design_role_names_the_design_role(self) -> None:
        for invalid in self.INVALID:
            with self.subTest(design=invalid):
                apps = applications()
                apps[DESIGN_PROVIDER]["services"][SERVICE_KEY][FLAVOR_KEY] = invalid
                with self.assertRaisesRegex(
                    ValueError,
                    rf"^{DESIGN_PROVIDER}: services\.{SERVICE_KEY}\.{FLAVOR_KEY} ",
                ):
                    cosmos_flavor(apps, APP)

    def test_an_invalid_flavor_fails_even_without_a_provider(self) -> None:
        apps = flavored(applications(provider=False), design=FLAVOR_FULL, app="sky")
        with self.assertRaisesRegex(ValueError, rf"^{APP}: "):
            cosmos_flavor(apps, APP)

    def test_an_active_provider_without_any_flavor_names_the_design_role(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ValueError,
            rf"^{DESIGN_PROVIDER}: services\.{SERVICE_KEY}\.{FLAVOR_KEY} is unset",
        ):
            cosmos_flavor(applications(), APP)


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


class TestEveryInTreeFlavorResolves(unittest.TestCase):
    def test_every_designed_role_resolves_a_valid_flavor_and_both_occur(
        self,
    ) -> None:
        apps = load_applications_from_roles_dir(PROJECT_ROOT / "roles")
        apps[PROVIDER] = {"services": {SERVICE_KEY: {"enabled": True, "shared": True}}}
        registry = build_service_registry_from_applications(apps)
        resolved = {}
        for role in designed_roles():
            with self.subTest(role=role):
                resolved[role] = _cosmos_flavor(apps, role, registry)
                self.assertIn(resolved[role], FLAVORS)
        self.assertEqual(set(resolved.values()), set(FLAVORS))


if __name__ == "__main__":
    unittest.main()
