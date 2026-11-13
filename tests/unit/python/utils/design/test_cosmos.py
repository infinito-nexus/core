from __future__ import annotations

import unittest

from utils.design.cosmos import DESIGN_PROVIDER
from utils.design.cosmos import cosmos_provider as _cosmos_provider
from utils.roles.applications.services.registry import (
    build_service_registry_from_applications,
)

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


if __name__ == "__main__":
    unittest.main()
