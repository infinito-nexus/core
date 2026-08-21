"""Contract between the swarm drill's completion marker and the roundtrip gate."""

from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text

DRILL = (
    PROJECT_ROOT / "scripts" / "tests" / "deploy" / "swarm" / "routine" / "00_one.sh"
)
GATE = PROJECT_ROOT / "scripts" / "tests" / "deploy" / "roundtrip.sh"
MARKER = "==> swarm drill complete: app="


class TestRoundtripMarker(unittest.TestCase):
    def setUp(self) -> None:
        self.drill = read_text(str(DRILL))
        self.gate = read_text(str(GATE))

    def test_the_drill_emits_the_marker(self) -> None:
        self.assertIn(MARKER, self.drill)

    def test_the_gate_looks_for_the_same_literal(self) -> None:
        self.assertIn(MARKER, self.gate)

    def test_the_marker_carries_the_app_id(self) -> None:
        emitted = re.search(rf'echo "{re.escape(MARKER)}(\S+)', self.drill)
        self.assertIsNotNone(emitted)
        self.assertEqual(emitted.group(1), "${APP_ID}")

    def test_the_app_id_is_guarded_against_being_empty(self) -> None:
        self.assertIn(': "${APP_ID:?', self.drill)

    def test_the_marker_is_emitted_after_the_state_assertion(self) -> None:
        assertion = self.drill.index("07_assert_state.sh")
        self.assertGreater(self.drill.index(MARKER), assertion)

    def test_the_gate_matches_the_marker_as_a_fixed_string(self) -> None:
        self.assertIn("grep -qF", self.gate)

    def test_the_gate_no_longer_matches_a_workflow_step_name(self) -> None:
        self.assertNotIn("provision/deploy/e2e/verify per round", self.gate)


if __name__ == "__main__":
    unittest.main()
