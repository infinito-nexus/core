from __future__ import annotations

import unittest
import unittest.mock

from cli.administration.deploy.dedicated import apps


class TestValidateApplicationIds(unittest.TestCase):
    def test_no_ids_does_nothing(self):
        # Should not raise
        apps.validate_application_ids("/etc/inventories/github-ci/devices.yml", [])

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
    def test_valid_ids_do_not_exit(self, mock_vdi_cls):
        instance = mock_vdi_cls.return_value
        instance.validate.return_value = {}

        # Should not exit
        apps.validate_application_ids(
            "/etc/inventories/github-ci/devices.yml",
            ["web-app-foo"],
        )

        instance.validate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
