from __future__ import annotations

import unittest
import unittest.mock

from cli.administration.deploy.dedicated import command as dedicated_command


class TestDedicatedCommandPassthrough(unittest.TestCase):
    @unittest.mock.patch(
        "cli.administration.deploy.dedicated.command.validate_application_ids"
    )
    @unittest.mock.patch(
        "cli.administration.deploy.dedicated.command.run_ansible_playbook"
    )
    @unittest.mock.patch(
        "cli.administration.deploy.dedicated.command.load_modes_from_yaml"
    )
    @unittest.mock.patch(
        "cli.administration.deploy.dedicated.command.add_dynamic_mode_args"
    )
    @unittest.mock.patch(
        "cli.administration.deploy.dedicated.command.build_modes_from_args"
    )
    def test_main_passes_unknown_ansible_args_through(
        self,
        mock_build_modes_from_args,
        mock_add_dynamic_mode_args,
        mock_load_modes_from_yaml,
        mock_run_ansible_playbook,
        mock_validate_application_ids,
    ):
        # Make dynamic modes a no-op for this test
        mock_load_modes_from_yaml.return_value = []
        mock_add_dynamic_mode_args.return_value = {}
        mock_build_modes_from_args.return_value = {}

        argv = [
            "/etc/inventories/github-ci/devices.yml",
            "--diff",
            # passthrough args (unknown to wrapper parser)
            "--tags",
            "deploy",
            "--check",
            "-e",
            "FOO=bar",
        ]

        rc = dedicated_command.main(argv)
        self.assertEqual(rc, 0)

        # validate_application_ids should be called with inventory + ids (empty list here)
        mock_validate_application_ids.assert_called_once()
        called_inventory, called_ids = mock_validate_application_ids.call_args.args
        self.assertEqual(called_inventory, "/etc/inventories/github-ci/devices.yml")
        self.assertEqual(called_ids, [])

        # run_ansible_playbook must be called once with ansible_args passthrough
        mock_run_ansible_playbook.assert_called_once()
        kwargs = mock_run_ansible_playbook.call_args.kwargs

        self.assertEqual(kwargs["inventory"], "/etc/inventories/github-ci/devices.yml")
        self.assertTrue(kwargs["diff"])

        self.assertIn("modes", kwargs)

        # Ensure old MODE_LOGS is not reintroduced
        self.assertNotIn("MODE_LOGS", kwargs["modes"])

        # Passthrough args must be preserved in order
        self.assertEqual(
            kwargs["ansible_args"],
            ["--tags", "deploy", "--check", "-e", "FOO=bar"],
        )


if __name__ == "__main__":
    unittest.main()
