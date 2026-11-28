"""Unit test: the hacker routine starts no scan without configured targets, and
every scan path passes the owner's production approval first."""

from __future__ import annotations

import unittest

from agents.routines import hacker_scan

_STEPS = {step.id: step for step in hacker_scan.STEPS}


def _next(step_id: str, state: dict) -> str:
    step = _STEPS[step_id]
    label = step.fn(dict(state))[step_id]
    return dict(step.branches)[label]


class TestTargets(unittest.TestCase):
    def test_without_targets_the_run_is_skipped(self) -> None:
        for state in ({}, {"targets": []}, {"targets": ""}):
            with self.subTest(state=state):
                target = _next("D1", state)
                self.assertEqual(target, "D0")
                self.assertEqual(_STEPS[target].kind, "terminal")

    def test_with_targets_the_run_goes_on_to_the_firewall(self) -> None:
        self.assertEqual(_next("D1", {"targets": ["shop.example.org"]}), "D2")

    def test_the_targets_check_is_a_decision(self) -> None:
        self.assertEqual(_STEPS["D1"].kind, "decision")


class TestProductionApproval(unittest.TestCase):
    def test_the_owner_ask_stands_between_the_targets_and_the_scan(self) -> None:
        self.assertEqual(_STEPS["D2"].nxt, "H1")
        self.assertEqual(_STEPS["H1"].kind, "ask")
        self.assertEqual([target for _, target in _STEPS["H1"].branches], ["D3", "D0"])

    def test_no_edge_reaches_the_scan_around_the_ask(self) -> None:
        sources = {
            step.id
            for step in hacker_scan.STEPS
            if step.nxt == "D3" or "D3" in dict(step.branches).values()
        }
        self.assertEqual(sources, {"H1"})


if __name__ == "__main__":
    unittest.main()
