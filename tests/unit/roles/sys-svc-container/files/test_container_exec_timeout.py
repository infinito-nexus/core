from __future__ import annotations

import importlib.util
import unittest
from unittest.mock import patch

from . import PROJECT_ROOT

CONTAINER_PY = PROJECT_ROOT / "roles" / "sys-svc-container" / "files" / "container.py"

spec = importlib.util.spec_from_file_location("container_exec_timeout", CONTAINER_PY)
container = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(container)


class TestParseExecTimeoutSeconds(unittest.TestCase):
    def test_units(self):
        self.assertEqual(container.parse_exec_timeout_seconds("45s"), 45)
        self.assertEqual(container.parse_exec_timeout_seconds("60min"), 3600)
        self.assertEqual(container.parse_exec_timeout_seconds("2h"), 7200)
        self.assertEqual(container.parse_exec_timeout_seconds("7d"), 604800)

    def test_bare_number_is_seconds(self):
        self.assertEqual(container.parse_exec_timeout_seconds("90"), 90)

    def test_invalid_raises(self):
        with self.assertRaises(ValueError):
            container.parse_exec_timeout_seconds("soon")


class TestExecTimeoutPrefix(unittest.TestCase):
    def test_unset_means_no_prefix(self):
        with patch.dict(container.os.environ, {}, clear=True):
            self.assertEqual(container.exec_timeout_prefix(), [])

    def test_zero_means_no_prefix(self):
        env = {"CONTAINER_EXEC_TIMEOUT": "0"}
        with patch.dict(container.os.environ, env, clear=True):
            self.assertEqual(container.exec_timeout_prefix(), [])

    def test_duration_builds_kill_prefix(self):
        env = {"CONTAINER_EXEC_TIMEOUT": "60min"}
        with patch.dict(container.os.environ, env, clear=True):
            self.assertEqual(
                container.exec_timeout_prefix(),
                ["timeout", "--kill-after=15", "3600"],
            )

    def test_week_default_builds_prefix(self):
        env = {"CONTAINER_EXEC_TIMEOUT": "7d"}
        with patch.dict(container.os.environ, env, clear=True):
            self.assertEqual(
                container.exec_timeout_prefix(),
                ["timeout", "--kill-after=15", "604800"],
            )


class TestMainExecDispatch(unittest.TestCase):
    def _run_main(self, argv, env):
        calls = []

        def _capture(cmd, debug):
            calls.append(cmd)
            return 0

        with (
            patch.object(container.sys, "argv", ["container", *argv]),
            patch.dict(container.os.environ, env, clear=True),
            patch.object(container, "exec_docker", side_effect=_capture),
        ):
            rc = container.main()
        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 1)
        return calls[0]

    def test_exec_gets_timeout_prefix(self):
        cmd = self._run_main(
            ["exec", "-i", "c1", "ls"], {"CONTAINER_EXEC_TIMEOUT": "60min"}
        )
        self.assertEqual(
            cmd,
            ["timeout", "--kill-after=15", "3600", "docker", "exec", "-i", "c1", "ls"],
        )

    def test_exec_without_env_is_plain_passthrough(self):
        cmd = self._run_main(["exec", "c1", "ls"], {})
        self.assertEqual(cmd, ["docker", "exec", "c1", "ls"])

    def test_other_subcommands_never_get_the_prefix(self):
        cmd = self._run_main(["ps", "-a"], {"CONTAINER_EXEC_TIMEOUT": "60min"})
        self.assertEqual(cmd, ["docker", "ps", "-a"])


if __name__ == "__main__":
    unittest.main()
