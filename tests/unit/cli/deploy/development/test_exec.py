from __future__ import annotations

import argparse
import os
import unittest
import unittest.mock

from cli.deploy.development import exec as exec_cmd


def _args(
    *,
    distro: str = "debian",
    cmd: list[str] | None = None,
    env: list[str] | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        distro=distro,
        cmd=cmd if cmd is not None else [],
        env=env if env is not None else [],
    )


class TestDevelopmentExec(unittest.TestCase):
    def test_handler_forwards_services_disabled(self):
        compose = unittest.mock.Mock()
        compose.exec.return_value.returncode = 0

        with unittest.mock.patch(
            "cli.deploy.development.exec.make_compose",
            return_value=compose,
        ):
            with unittest.mock.patch.dict(
                os.environ, {"SERVICES_DISABLED": "email"}, clear=False
            ):
                rc = exec_cmd.handler(_args(cmd=["--", "sh", "-lc", "true"]))

        self.assertEqual(rc, 0)
        compose.exec.assert_called_once_with(
            ["sh", "-lc", "true"],
            check=False,
            extra_env={"SERVICES_DISABLED": "email"},
        )

    def test_handler_omits_extra_env_when_services_disabled_unset(self):
        compose = unittest.mock.Mock()
        compose.exec.return_value.returncode = 0

        env = {k: v for k, v in os.environ.items() if k != "SERVICES_DISABLED"}
        with unittest.mock.patch(
            "cli.deploy.development.exec.make_compose",
            return_value=compose,
        ):
            with unittest.mock.patch.dict(os.environ, env, clear=True):
                rc = exec_cmd.handler(_args(cmd=["echo", "hi"]))

        self.assertEqual(rc, 0)
        compose.exec.assert_called_once_with(
            ["echo", "hi"], check=False, extra_env=None
        )

    def test_handler_requires_command(self):
        with self.assertRaises(SystemExit):
            exec_cmd.handler(_args(cmd=[]))

    def test_env_pairs_are_injected_into_extra_env(self):
        compose = unittest.mock.Mock()
        compose.exec.return_value.returncode = 0

        env = {k: v for k, v in os.environ.items() if k != "SERVICES_DISABLED"}
        with unittest.mock.patch(
            "cli.deploy.development.exec.make_compose",
            return_value=compose,
        ):
            with unittest.mock.patch.dict(os.environ, env, clear=True):
                rc = exec_cmd.handler(
                    _args(
                        cmd=["bash", "/opt/helper.sh"],
                        env=["INVENTORY_FILE=/srv/inv/devices.yml", "APPS=web-app-foo"],
                    )
                )

        self.assertEqual(rc, 0)
        compose.exec.assert_called_once_with(
            ["bash", "/opt/helper.sh"],
            check=False,
            extra_env={
                "INVENTORY_FILE": "/srv/inv/devices.yml",
                "APPS": "web-app-foo",
            },
        )

    def test_env_pair_with_equals_in_value_is_preserved(self):
        compose = unittest.mock.Mock()
        compose.exec.return_value.returncode = 0

        env = {k: v for k, v in os.environ.items() if k != "SERVICES_DISABLED"}
        with unittest.mock.patch(
            "cli.deploy.development.exec.make_compose",
            return_value=compose,
        ):
            with unittest.mock.patch.dict(os.environ, env, clear=True):
                exec_cmd.handler(_args(cmd=["true"], env=["EXTRA_VARS=a=1 b=2"]))

        # Only the first '=' splits key from value; everything after stays intact.
        compose.exec.assert_called_once_with(
            ["true"],
            check=False,
            extra_env={"EXTRA_VARS": "a=1 b=2"},
        )

    def test_env_pair_overrides_implicit_services_disabled(self):
        compose = unittest.mock.Mock()
        compose.exec.return_value.returncode = 0

        with unittest.mock.patch(
            "cli.deploy.development.exec.make_compose",
            return_value=compose,
        ):
            with unittest.mock.patch.dict(
                os.environ, {"SERVICES_DISABLED": "from-env"}, clear=False
            ):
                exec_cmd.handler(
                    _args(cmd=["true"], env=["SERVICES_DISABLED=from-cli"])
                )

        compose.exec.assert_called_once_with(
            ["true"],
            check=False,
            extra_env={"SERVICES_DISABLED": "from-cli"},
        )

    def test_env_pair_without_equals_is_rejected(self):
        compose = unittest.mock.Mock()
        with unittest.mock.patch(
            "cli.deploy.development.exec.make_compose",
            return_value=compose,
        ):
            with self.assertRaisesRegex(SystemExit, "expects KEY=VALUE"):
                exec_cmd.handler(_args(cmd=["true"], env=["BARE"]))

    def test_env_pair_with_empty_key_is_rejected(self):
        compose = unittest.mock.Mock()
        with unittest.mock.patch(
            "cli.deploy.development.exec.make_compose",
            return_value=compose,
        ):
            with self.assertRaisesRegex(SystemExit, "KEY is empty"):
                exec_cmd.handler(_args(cmd=["true"], env=["=value"]))


if __name__ == "__main__":
    unittest.main()
