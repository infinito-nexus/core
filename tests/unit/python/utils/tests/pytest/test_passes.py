"""``utils.tests.pytest.passes`` prints what ``-rP`` printed, in linear time.

Passing tests print warnings such as ``[WARNING] External URL unverified`` that
only the PASSES section shows, so the plugin must print that section exactly as
pytest's ``-rP`` does, captured teardown output and worker lines included.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from utils import PROJECT_ROOT
from utils.tests.pytest.passes import teardowns_by_node

SAMPLE = """
import warnings

import pytest


@pytest.fixture
def noisy():
    yield
    print("teardown-note")


def test_unverified_url(noisy):
    print("[WARNING] External URL unverified https://example.invalid")


def test_python_warning():
    warnings.warn("MirrorCheckWarning: mirror unchecked", UserWarning)


def test_quiet():
    pass
"""
URL_WARNING = "[WARNING] External URL unverified https://example.invalid"
MASK_LINE = "::add-mask::throwaway-generated-value"
MASK_SAMPLE = f"""
import sys


def test_generates_a_credential():
    print("{MASK_LINE}", file=sys.stderr)
    print("{URL_WARNING}")
"""


def _passes_section(output: str) -> list[str]:
    lines = output.splitlines()
    start = next(i for i, line in enumerate(lines) if " PASSES " in line)
    end = next(i for i in range(start + 1, len(lines)) if lines[i][:1].isdigit())
    return lines[start:end]


class TestPassesSection(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "test_sample.py").write_text(SAMPLE)

    def _pytest(self, *flags: str) -> str:
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            filter(None, (str(PROJECT_ROOT), env.get("PYTHONPATH")))
        )
        env.pop("PYTEST_ADDOPTS", None)
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                *flags,
                "test_sample.py",
            ],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc.stdout

    def test_warnings_of_passing_tests_stay_visible(self) -> None:
        output = self._pytest("-p", "utils.tests.pytest.passes")

        self.assertIn(URL_WARNING, output)
        self.assertIn("teardown-note", output)
        self.assertIn("MirrorCheckWarning: mirror unchecked", output)

    def test_without_the_plugin_or_rp_the_url_warning_is_hidden(self) -> None:
        output = self._pytest()

        self.assertNotIn(URL_WARNING, output)
        self.assertIn("MirrorCheckWarning: mirror unchecked", output)

    def test_the_section_equals_the_rp_section_under_xdist(self) -> None:
        stock = self._pytest("-n", "1", "-rP")
        plugin = self._pytest("-n", "1", "-p", "utils.tests.pytest.passes")

        self.assertEqual(_passes_section(plugin), _passes_section(stock))

    def test_mask_commands_of_passing_tests_never_reach_the_runner(self) -> None:
        (self.root / "test_sample.py").write_text(MASK_SAMPLE)

        plugin = _passes_section(self._pytest("-p", "utils.tests.pytest.passes"))
        stock = _passes_section(self._pytest("-rP"))

        self.assertIn(MASK_LINE, stock)
        self.assertNotIn(MASK_LINE, plugin)
        self.assertIn(URL_WARNING, plugin)


class TestTeardownIndex(unittest.TestCase):
    def test_teardowns_are_grouped_by_node_in_order(self) -> None:
        reports = [
            SimpleNamespace(when="setup", nodeid="a"),
            SimpleNamespace(when="teardown", nodeid="a", tag=1),
            SimpleNamespace(when="teardown", nodeid="b", tag=2),
            SimpleNamespace(when="teardown", nodeid="a", tag=3),
        ]

        grouped = teardowns_by_node(reports)

        self.assertEqual([r.tag for r in grouped["a"]], [1, 3])
        self.assertEqual([r.tag for r in grouped["b"]], [2])
        self.assertNotIn("c", grouped)


if __name__ == "__main__":
    unittest.main()
