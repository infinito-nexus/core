from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from plugins.filter.merge.with_defaults import merge_with_defaults
from utils.cache.applications import get_application_defaults
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT
from .test_disc_space import _provisioned_vars
from .test_mirror import _block

HLTH_RUNTIME = (
    PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "test" / "hlth_runtime.py"
)
ROLE = "sys-ctl-hlth-runtime"
DEVELOPMENT_INVENTORY = next(
    line.partition("=")[2]
    for line in read_text(str(PROJECT_ROOT / "default.env")).splitlines()
    if line.startswith("INFINITO_INVENTORY_VARS_FILE=")
)
DEVELOPMENT = load_yaml_any(str(PROJECT_ROOT / DEVELOPMENT_INVENTORY))["applications"][
    ROLE
]
DEFAULTS = get_application_defaults(roles_dir=str(PROJECT_ROOT / "roles"))


def _severity(overrides: dict) -> dict:
    merged = merge_with_defaults({ROLE: DEFAULTS[ROLE]}, overrides)
    return merged[ROLE]["services"]["runtime"]["severity"]


STACK = _severity({ROLE: DEVELOPMENT})
STACK_ENV = {"DOCS_TEST_HLTH_RUNTIME_SEVERITY": json.dumps(STACK)}


def _inject(block: str, environment: dict[str, str]) -> str:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "block.sh"
        path.write_text(block, encoding="utf-8")
        subprocess.run(
            [sys.executable, str(HLTH_RUNTIME), str(path)],
            check=True,
            capture_output=True,
            env={"PATH": os.environ["PATH"], **environment},
            text=True,
        )
        return path.read_text(
            encoding="utf-8"
        )  # nocheck: cache-read -- hlth_runtime.py rewrote this tempfile in the same flow


class TestHlthRuntime(unittest.TestCase):
    def test_the_replay_provisions_the_stack_severity(self) -> None:
        for is_host in (False, True):
            with self.subTest(is_host=is_host):
                published = _block(is_host=is_host)
                provisioned = _provisioned_vars(_inject(published, STACK_ENV))
                carried = provisioned["applications"][ROLE]["services"]["runtime"]
                self.assertEqual(carried["severity"], STACK)
                for severity, action in DEVELOPMENT["services"]["runtime"][
                    "severity"
                ].items():
                    self.assertEqual(carried["severity"][severity], action)
                self.assertEqual(
                    provisioned,
                    {
                        **_provisioned_vars(published),
                        "applications": {ROLE: {"services": {"runtime": carried}}},
                    },
                )

    def test_the_target_judges_critical_findings_like_the_development_inventory(
        self,
    ) -> None:
        provisioned = _provisioned_vars(_inject(_block(is_host=False), STACK_ENV))
        critical = _severity(provisioned["applications"])["CRITICAL"]
        self.assertEqual(
            critical, DEVELOPMENT["services"]["runtime"]["severity"]["CRITICAL"]
        )
        self.assertNotEqual(critical, _severity({})["CRITICAL"])

    def test_both_shapes_still_parse_as_bash(self) -> None:
        for is_host in (False, True):
            with self.subTest(is_host=is_host):
                injected = _inject(_block(is_host=is_host), STACK_ENV)
                subprocess.run(["bash", "-n"], input=injected, check=True, text=True)

    def test_vars_that_already_set_applications_are_a_failure(self) -> None:
        block = _block(is_host=False).replace(
            '--vars "{', '--vars "{\\"applications\\": {}, ', 1
        )
        with self.assertRaises(subprocess.CalledProcessError) as raised:
            _inject(block, STACK_ENV)
        self.assertEqual(raised.exception.returncode, 1)
        self.assertIn("already carry", raised.exception.stderr)

    def test_a_block_without_vars_is_a_failure(self) -> None:
        with self.assertRaises(subprocess.CalledProcessError) as raised:
            _inject("echo nothing to provision\n", STACK_ENV)
        self.assertEqual(raised.exception.returncode, 1)
        self.assertIn("no single --vars object", raised.exception.stderr)


if __name__ == "__main__":
    unittest.main()
