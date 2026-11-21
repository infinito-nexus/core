from __future__ import annotations

import re
import unittest
from typing import Any

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles/web-app-odoo"
MODULE_OPS = ROLE / "tasks/03_install_modules/module_ops.yml"
GUARD = "fs_attachment_s3_installed"
PIN = re.compile(
    r"^odoo-addon-(?P<module>[A-Za-z0-9_.-]+)==(?P<version>\S+)", re.MULTILINE
)
INSTALLED_ON_19 = [["fs_attachment_s3", "19.0.1.2.1"]]


def series(version: str) -> Any:
    """Args:
        version: the ``odoo`` image tag, as ``ODOO_VERSION`` carries it.

    Returns:
        The role's ``ODOO_SERIES`` rendered for that tag.
    """
    expression = load_yaml(ROLE / ROLE_FILE_VARS_MAIN)["ODOO_SERIES"]
    templar = Templar(loader=DataLoader(), variables={"ODOO_VERSION": version})
    return templar.template(trust_as_template(expression))


def guard_fails(version: str, rows: list[list[str]], objstore: bool) -> Any:
    """Args:
        version: the ``odoo`` image tag the role deploys.
        rows: what ``installed-module.sql`` returns, one ``[name, latest_version]``
            per installed module.
        objstore: ``ODOO_OBJSTORE_ENABLED``.

    Returns:
        ``None`` when the task's ``when`` skips it, else its ``failed_when``.
    """
    tasks = DataLoader().load_from_file(str(MODULE_OPS), trusted_as_template=True)
    task = next(task for task in tasks if task.get("register") == GUARD)
    templar = Templar(
        loader=DataLoader(),
        variables={
            "ODOO_OBJSTORE_ENABLED": objstore,
            "ODOO_SERIES": series(version),
            GUARD: {"rows": rows},
        },
    )
    if not templar.template(trust_as_template("{{ " + task["when"] + " }}")):
        return None
    return templar.template(trust_as_template("{{ " + task["failed_when"] + " }}"))


class TestShippedAddons(unittest.TestCase):
    def test_every_oca_pin_carries_the_series_of_the_image(self):
        image = load_yaml(ROLE / ROLE_FILE_META_SERVICES)["odoo"]["version"]
        pins = {
            match["module"]: match["version"]
            for path in sorted((ROLE / "files/pip").glob("*.txt"))
            for match in PIN.finditer(read_text(str(path)))
        }
        self.assertTrue(pins, "no odoo-addon-* pin found under files/pip")
        self.assertEqual(
            sorted(
                f"{module}=={version}"
                for module, version in pins.items()
                if not version.startswith(f"{series(image)}.")
            ),
            [],
            f"Odoo {image} marks a module of another series as not installable "
            "and only warns, so `odoo -i` exits 0 without creating its tables; "
            "move the odoo image and these pins to one series together",
        )

    def test_the_guard_is_skipped_without_the_object_store(self):
        self.assertIsNone(guard_fails("19.0", [], objstore=False))

    def test_the_guard_passes_the_addon_installed_for_the_image_series(self):
        for version in ("19.0", "19.0-20261112"):
            with self.subTest(version=version):
                self.assertFalse(guard_fails(version, INSTALLED_ON_19, objstore=True))

    def test_the_guard_fails_when_odoo_refused_to_install_the_addon(self):
        self.assertTrue(
            guard_fails("20.0", [], objstore=True),
            "a fresh database on Odoo 20 leaves the 19.0 addon uninstallable and "
            "`odoo -i` exits 0, so the object store task hits a missing fs_storage",
        )

    def test_the_guard_fails_on_the_addon_installed_for_another_series(self):
        self.assertTrue(
            guard_fails("20.0", INSTALLED_ON_19, objstore=True),
            "a 19.0 database on Odoo 20 keeps the addon 'installed' while the "
            "loader skips it, so attachments silently stop going to the store",
        )

    def test_the_guard_fails_closed_on_a_tag_without_a_series(self):
        self.assertTrue(guard_fails("latest", INSTALLED_ON_19, objstore=True))


if __name__ == "__main__":
    unittest.main()
