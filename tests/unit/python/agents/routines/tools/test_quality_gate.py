"""Unit test: the gate verdict reads the FAILED TARGETS line of a recorded gate
log and ignores the exit status the tee pipe reports."""

from __future__ import annotations

import unittest

from agents.routines.tools.quality_gate import failed_targets, gate_green

_GREEN = """📊 per-target wall-clock
  test-unit        41.2s
  lint-python       8.7s
FAILED TARGETS:
make[1]: Leaving directory
"""

_RED = """📊 per-target wall-clock
  test-unit        41.2s
  lint-python       8.7s
FAILED TARGETS: lint-python test-integration
make: *** [Makefile:12: quality] Error 2
"""

_TEE_SUCCESS = """FAILED TARGETS: test-unit
... | tee /tmp/make-quality.log
Exited with code 0
"""


class TestQualityGate(unittest.TestCase):
    def test_green_when_failed_line_empty(self) -> None:
        self.assertEqual(failed_targets(_GREEN), [])
        self.assertTrue(gate_green(_GREEN))

    def test_red_lists_failed_targets(self) -> None:
        self.assertEqual(failed_targets(_RED), ["lint-python", "test-integration"])
        self.assertFalse(gate_green(_RED))

    def test_exit_code_zero_does_not_override_failed_targets(self) -> None:
        self.assertEqual(failed_targets(_TEE_SUCCESS), ["test-unit"])
        self.assertFalse(gate_green(_TEE_SUCCESS))


if __name__ == "__main__":
    unittest.main()
