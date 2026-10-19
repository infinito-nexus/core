#!/usr/bin/env python3
import contextlib
import importlib.util
import io
import sys
from unittest import TestCase, main, mock

from . import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles" / "sys-svc-journalctl" / "files" / "python" / "active_rate_limit.py"


def load_script():
    spec = importlib.util.spec_from_file_location("active_rate_limit", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_readlink(exports):
    def readlink(path):
        if path in exports:
            return exports[path]
        raise FileNotFoundError(path)

    return readlink


class TestActiveRateLimit(TestCase):
    def setUp(self):
        self.script = load_script()

    def output(self, exports):
        stdout = io.StringIO()
        with (
            mock.patch.object(self.script.os, "readlink", side_effect=fake_readlink(exports)),
            mock.patch.object(sys, "argv", ["active_rate_limit.py", "docker.service"]),
            contextlib.redirect_stdout(stdout),
        ):
            self.script.main()
        return stdout.getvalue().strip()

    def test_exported_limit_is_read(self):
        self.assertEqual(
            self.output(
                {
                    "/run/systemd/units/log-rate-limit-interval:docker.service": "30000000",
                    "/run/systemd/units/log-rate-limit-burst:docker.service": "50000",
                }
            ),
            "30000000 50000",
        )

    def test_a_unit_without_its_own_limit_prints_dashes(self):
        self.assertEqual(self.output({}), "- -")


if __name__ == "__main__":
    main()
