from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from cli.administration.deploy.swarm import command


class TestSwarmMain(unittest.TestCase):
    def test_custom_roles_are_pulled_before_the_closure_reads_roles(self):
        calls: list[str] = []
        args = SimpleNamespace(id=["web-app-cst-demo"], inventory="inv/devices.yml")

        def closure(ids, _inventory):
            calls.append("closure")
            return ids

        with (
            mock.patch.object(command, "parse_args", return_value=(args, [], {})),
            mock.patch.object(
                command,
                "pull_custom_roles",
                side_effect=lambda _args: calls.append("pull"),
            ),
            mock.patch.object(command, "swarm_deploy_targets", side_effect=closure),
            mock.patch.object(command, "run_from_args", return_value=0) as run,
        ):
            self.assertEqual(0, command.main([]))

        self.assertEqual(["pull", "closure"], calls)
        run.assert_called_once_with(args, [], {})


if __name__ == "__main__":
    unittest.main()
