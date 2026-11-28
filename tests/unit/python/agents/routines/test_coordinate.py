"""Unit test: the coordinator routine reports diverging version pins of two
feature branches to both branch owners' accounts, and stays quiet while the
pins agree."""

from __future__ import annotations

import unittest

from agents.routines import coordinate

_STEPS = {step.id: step for step in coordinate.STEPS}
_FEATURE_A = "langgraph==0.2.60\nimage: postgres:16.4\nrequests==2.32.3\n"
_FEATURE_B = "langgraph==0.2.74\nimage: postgres:17.0\nrequests==2.32.3\n"


def _branches(pins_b: str, owner_b: str = "kevin") -> list[dict]:
    return [
        {"name": "feature/a", "owner": "impl0alice", "pins": _FEATURE_A},
        {"name": "feature/b", "owner": owner_b, "pins": pins_b},
    ]


def _run(branches: list[dict]) -> tuple[str, dict]:
    state = _STEPS["D2"].fn({"branches": branches})
    target = dict(_STEPS["D2"].branches)[state["D2"]]
    if target == "D3":
        state = _STEPS["D3"].fn(state)
    return target, state


class TestPinDrift(unittest.TestCase):
    def test_a_drift_is_addressed_to_both_owners(self) -> None:
        target, state = _run(_branches(_FEATURE_B))
        self.assertEqual(target, "D3")
        self.assertEqual(state["drift"], ["langgraph", "postgres"])
        self.assertEqual(
            [notice["recipient"] for notice in state["notices"]],
            ["impl0alice", "kevin"],
        )
        for notice in state["notices"]:
            with self.subTest(recipient=notice["recipient"]):
                self.assertIn("feature/a and feature/b", notice["text"])
                self.assertIn("langgraph, postgres", notice["text"])

    def test_agreeing_pins_report_nothing(self) -> None:
        target, state = _run(_branches(_FEATURE_A))
        self.assertEqual(target, "D0")
        self.assertEqual(_STEPS[target].kind, "terminal")
        self.assertNotIn("notices", state)

    def test_a_session_id_owner_is_not_addressed(self) -> None:
        session = "0f0e0d0c-0b0a-0908-0706-050403020100"
        _, state = _run(_branches(_FEATURE_B, owner_b=session))
        self.assertEqual(
            [notice["recipient"] for notice in state["notices"]], ["impl0alice"]
        )
        self.assertEqual(state["unaddressed"], [session])

    def test_the_report_ends_before_the_branches_meet(self) -> None:
        self.assertEqual(_STEPS["D3"].nxt, "D4")
        self.assertEqual(_STEPS["D4"].kind, "terminal")
        self.assertFalse([s for s in coordinate.STEPS if s.kind == "model"])


if __name__ == "__main__":
    unittest.main()
