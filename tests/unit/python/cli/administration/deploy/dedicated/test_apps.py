from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from cli.administration.deploy.dedicated import apps


class TestValidateApplicationIds(unittest.TestCase):
    @unittest.mock.patch("utils.roles.validation.deploy_id.ValidDeployId")
    def test_no_ids_does_nothing(self, mock_vdi_cls):
        self.assertIsNone(
            apps.validate_application_ids("/etc/inventories/github-ci/devices.yml", [])
        )
        mock_vdi_cls.assert_not_called()

    @unittest.mock.patch("utils.roles.validation.deploy_id.ValidDeployId")
    def test_invalid_ids_raise_system_exit(self, mock_vdi_cls):
        instance = mock_vdi_cls.return_value
        instance.validate.return_value = {
            "web-app-foo": {"allowed": False, "in_inventory": True},
            "web-app-bar": {"allowed": True, "in_inventory": False},
        }

        with self.assertRaises(SystemExit) as ctx:
            apps.validate_application_ids(
                "/etc/inventories/github-ci/devices.yml",
                ["web-app-foo", "web-app-bar"],
            )

        self.assertEqual(ctx.exception.code, 1)
        instance.validate.assert_called_once_with(
            "/etc/inventories/github-ci/devices.yml",
            ["web-app-foo", "web-app-bar"],
        )

    @unittest.mock.patch("utils.roles.validation.deploy_id.ValidDeployId")
    def test_invalid_ids_never_print_the_inventory_content(self, mock_vdi_cls):
        mock_vdi_cls.return_value.validate.return_value = {
            "web-app-typo": {"in_roles": False}
        }
        with tempfile.TemporaryDirectory() as tmp:
            inventory = Path(tmp) / "devices.yml"
            inventory.write_text(
                "all:\n  vars:\n    ansible_become_password: s3cr3t-marker\n",
                encoding="utf-8",
            )
            out = io.StringIO()
            with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
                apps.validate_application_ids(str(inventory), ["web-app-typo"])

        self.assertIn(str(inventory), out.getvalue())
        self.assertIn("web-app-typo: not defined as a role", out.getvalue())
        self.assertNotIn("s3cr3t-marker", out.getvalue())

    @unittest.mock.patch("utils.roles.validation.deploy_id.ValidDeployId")
    def test_valid_ids_do_not_exit(self, mock_vdi_cls):
        instance = mock_vdi_cls.return_value
        instance.validate.return_value = {}

        apps.validate_application_ids(
            "/etc/inventories/github-ci/devices.yml",
            ["web-app-foo"],
        )

        instance.validate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
