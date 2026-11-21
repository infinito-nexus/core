from __future__ import annotations

import shutil
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from plugins.lookup import design
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.applications.services.registry import (
    load_applications_from_roles_dir,
)
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

PROVIDER = "web-app-cst-cosmos"
DESIGN = "web-svc-design"
SILENT = "web-svc-html"
FORBIDDING = "web-app-forbids-the-sky"
BRANDING = {
    "logo": False,
    "title": False,
    "name": "Fixture",
    "label": "Fixture",
    "bootstrap": False,
    "slots": {},
}


def _role(roles: Path, name: str, services: str) -> None:
    (roles / name / ROLE_FILE_VARS_MAIN).parent.mkdir(parents=True)
    (roles / name / ROLE_FILE_META_SERVICES).parent.mkdir(parents=True)
    (roles / name / ROLE_FILE_VARS_MAIN).write_text(
        f"application_id: {name}\n", encoding="utf-8"
    )
    (roles / name / ROLE_FILE_META_SERVICES).write_text(services, encoding="utf-8")


def checkout(root: Path, pulled: bool, design_services: str | None = None) -> None:
    """
    Args:
        root: the empty playbook directory to fill.
        pulled: whether the cosmos provider role is placed under ``roles/``.
        design_services: the ``meta/services.yml`` of the design role, or None
            for the in-tree file.
    """
    roles = root / "roles"
    for name in (DESIGN, SILENT):
        source = PROJECT_ROOT / "roles" / name
        (roles / name / "meta").mkdir(parents=True)
        (roles / name / "vars").mkdir()
        shutil.copyfile(
            source / ROLE_FILE_VARS_MAIN, roles / name / ROLE_FILE_VARS_MAIN
        )
        shutil.copyfile(
            source / ROLE_FILE_META_SERVICES, roles / name / ROLE_FILE_META_SERVICES
        )
    if design_services is not None:
        (roles / DESIGN / ROLE_FILE_META_SERVICES).write_text(
            design_services, encoding="utf-8"
        )
    _role(roles, FORBIDDING, "cosmos:\n  enabled: false\n")
    if pulled:
        _role(roles, PROVIDER, "cosmos:\n  enabled: true\n  shared: true\n")


def lookup(root: Path, application_id: str) -> dict:
    """
    Args:
        root: the playbook directory :func:`checkout` filled.
        application_id: the designed role to resolve.

    Returns:
        The one entry ``lookup('design', application_id)`` returns.
    """
    applications = load_applications_from_roles_dir(root / "roles")
    tree = {"img": f"/cdn/roles/{application_id}/latest/img"}
    answers = {
        "applications": applications,
        "cdn": {
            "role": {"release": tree},
            "urls": {"role": {"release": tree}},
            "relative_urls": {"role": {"release": tree}},
        },
        "domain": f"{application_id}.example",
    }

    def sub(_self, name, _terms, _variables):
        return answers[name]

    with (
        mock.patch.object(design.LookupModule, "_sub", sub),
        mock.patch.object(design, "resolve_branding", return_value=dict(BRANDING)),
    ):
        return design.LookupModule().run(
            [application_id], variables={"playbook_dir": str(root)}
        )[0]


class TestTheDesignLookupResolvesTheProviderFromTheRolesDirectory(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_a_checkout_with_the_pulled_role_names_it_for_a_silent_role(self) -> None:
        checkout(self.root, pulled=True)
        self.assertEqual(lookup(self.root, SILENT)["cosmos"], PROVIDER)

    def test_a_role_that_forbids_the_sky_gets_none(self) -> None:
        checkout(self.root, pulled=True)
        self.assertEqual(lookup(self.root, FORBIDDING)["cosmos"], "")

    def test_a_checkout_without_the_pulled_role_gets_none(self) -> None:
        checkout(self.root, pulled=False)
        self.assertEqual(lookup(self.root, SILENT)["cosmos"], "")

    def test_a_design_role_that_switches_cosmos_off_gets_none(self) -> None:
        services = load_yaml_str(
            read_text(str(PROJECT_ROOT / "roles" / DESIGN / ROLE_FILE_META_SERVICES))
        )
        self.assertEqual(services["cosmos"]["enabled"], True)
        self.assertEqual(services["cosmos"]["shared"], True)
        checkout(
            self.root,
            pulled=True,
            design_services="cosmos:\n  enabled: false\n  shared: true\n",
        )
        self.assertEqual(lookup(self.root, SILENT)["cosmos"], "")


if __name__ == "__main__":
    unittest.main()
