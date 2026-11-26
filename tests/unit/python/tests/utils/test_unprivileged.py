from __future__ import annotations

import contextlib
import os
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tests.utils import unprivileged as unprivileged_mod

PASSED = "1 passed in 0.10s\n"


def _probe() -> unittest.TestCase:
    class Probe(unittest.TestCase):
        ran: list[int]

        @unprivileged_mod.unprivileged
        def test_body(self) -> None:
            self.ran.append(os.geteuid())

    probe = Probe("test_body")
    probe.ran = []
    return probe


@contextlib.contextmanager
def _as_root(returncode: int, stdout: str):
    child = subprocess.CompletedProcess(["pytest"], returncode, stdout, "")
    with (
        patch.object(unprivileged_mod.os, "geteuid", return_value=0),
        patch.object(unprivileged_mod, "unprivileged_ids", return_value=(1000, 1000)),
        patch.object(unprivileged_mod, "run_dropped", return_value=child) as dropped,
    ):
        yield dropped


class TestUnprivileged(unittest.TestCase):
    def setUp(self) -> None:
        self.probe = _probe()

    def test_an_unprivileged_caller_runs_the_body_inline(self) -> None:
        with (
            patch.object(unprivileged_mod.os, "geteuid", return_value=1000),
            patch.object(unprivileged_mod, "run_dropped") as dropped,
        ):
            self.probe.test_body()
        self.assertEqual(len(self.probe.ran), 1)
        dropped.assert_not_called()

    def test_root_never_runs_the_body_itself(self) -> None:
        with _as_root(0, PASSED) as dropped:
            self.probe.test_body()
        self.assertEqual(self.probe.ran, [])
        node, uid, gid = dropped.call_args.args
        self.assertTrue(node.startswith(f"{__file__}::"), node)
        self.assertTrue(node.endswith("::Probe::test_body"), node)
        self.assertEqual((uid, gid), (1000, 1000))

    def test_a_failing_child_fails_the_test(self) -> None:
        with _as_root(1, "1 failed in 0.10s\n"), self.assertRaises(AssertionError):
            self.probe.test_body()

    def test_a_child_that_ran_more_than_its_test_fails_the_test(self) -> None:
        with _as_root(0, "11 passed in 0.10s\n"), self.assertRaises(AssertionError):
            self.probe.test_body()

    def test_a_skipping_child_skips_the_test_with_its_reason(self) -> None:
        out = "SKIPPED [1] tests/x.py:12: no walk misses it\n1 skipped in 0.10s\n"
        with _as_root(0, out), self.assertRaises(unittest.SkipTest) as skipped:
            self.probe.test_body()
        self.assertIn("no walk misses it", str(skipped.exception))

    def test_a_class_gets_each_own_test_method_wrapped(self) -> None:
        @unprivileged_mod.unprivileged
        class Case(unittest.TestCase):
            def test_one(self) -> None:
                raise AssertionError("ran as root")

            def helper(self) -> str:
                return "untouched"

        case = Case("test_one")
        with _as_root(0, PASSED) as dropped:
            case.test_one()
        dropped.assert_called_once()
        self.assertEqual(case.helper(), "untouched")


class TestUnprivilegedIds(unittest.TestCase):
    def _ids(self, uid: int, gid: int) -> tuple[int, int]:
        root = MagicMock()
        root.stat.return_value = SimpleNamespace(st_uid=uid, st_gid=gid)
        with patch.object(unprivileged_mod, "PROJECT_ROOT", root):
            return unprivileged_mod.unprivileged_ids()

    def test_the_checkout_owner_runs_the_child(self) -> None:
        self.assertEqual(self._ids(1000, 1001), (1000, 1001))

    def test_a_root_owned_checkout_drops_to_nobody(self) -> None:
        self.assertEqual(
            self._ids(0, 0), (unprivileged_mod.NOBODY, unprivileged_mod.NOBODY)
        )


if __name__ == "__main__":
    unittest.main()
