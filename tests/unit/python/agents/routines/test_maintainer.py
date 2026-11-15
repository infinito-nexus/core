"""Unit test: the maintainer routine's decision nodes route on parsed evidence,
the push follows the matrix prediction and the labels, a review reply follows
the push and the read of the next automated review, and a stub run (model nodes
as passthroughs) reaches a terminal."""

from __future__ import annotations

import importlib.util
import unittest

from agents.routines import maintainer
from agents.routines.tools.affected import MATRIX_LABEL

_HAVE_LANGGRAPH = importlib.util.find_spec("langgraph") is not None


def reachable(steps: list, start: str, without: str) -> set[str]:
    """Return the step ids reachable from ``start`` when ``without`` is cut out.

    Args:
        steps: a routine's ``STEPS``.
        start: the id the walk starts at.
        without: the id no path may pass through.
    """
    targets = {
        step.id: ([step.nxt] if step.nxt else []) + [t for _, t in step.branches]
        for step in steps
    }
    seen: set[str] = set()
    todo = [start]
    while todo:
        current = todo.pop()
        if current in seen or current == without:
            continue
        seen.add(current)
        todo.extend(targets[current])
    return seen


class TestMaintainerOrder(unittest.TestCase):
    def assert_only_after(self, later: str, earlier: str) -> None:
        self.assertIn(later, reachable(maintainer.STEPS, "T1", ""))
        self.assertNotIn(later, reachable(maintainer.STEPS, "T1", earlier))

    def test_the_labels_are_set_before_the_push(self) -> None:
        self.assert_only_after("D8", "D17")

    def test_the_matrix_is_predicted_before_the_push(self) -> None:
        self.assert_only_after("D8", "D16")

    def test_a_review_reply_follows_the_push(self) -> None:
        self.assert_only_after("D12", "D8")

    def test_a_review_reply_follows_the_read_of_the_next_review(self) -> None:
        self.assert_only_after("D12", "D18")


_FATAL = 'fatal: [localhost]: FAILED! => {"msg": "port 3000 never opened"}\n'
_SUPERSEDED = (
    "Canceling since a higher priority waiting request for ci-x exists\n"
    "✗ Finish pipeline\n"
)
_CLASS_FIXTURES = (
    (maintainer.JUDGEMENT, [], [_FATAL], "L1"),
    (
        maintainer.STARVED,
        [{"name": "deploy", "steps": [], "runner_name": ""}],
        [],
        "C2",
    ),
    (
        maintainer.SUPERSEDED,
        [],
        [_SUPERSEDED],
        "C3",
    ),
    (maintainer.UNATTRIBUTED, [], ["404: Not Found\n"], "C4"),
    (
        maintainer.BUDGET_KILL,
        [],
        ["FAILED TARGETS:\nmake: *** [test] Error 124\n"],
        "C5",
    ),
    (
        maintainer.EXTERNAL,
        [],
        ["Error response from daemon: toomanyrequests: pull rate limit\n", _FATAL],
        "C6",
    ),
)


class TestFailureClassRouter(unittest.TestCase):
    def test_every_fixture_routes_to_its_branch(self) -> None:
        branches = dict(
            next(step for step in maintainer.STEPS if step.id == "C1").branches
        )
        for label, jobs, logs, target in _CLASS_FIXTURES:
            with self.subTest(label=label):
                state = maintainer._route_class({"jobs": jobs, "job_logs": logs})
                self.assertEqual(state["C1"], label)
                self.assertEqual(branches[state["C1"]], target)

    def test_a_citable_line_beside_a_404_needs_judgement(self) -> None:
        logs = ["404: Not Found\n", _FATAL]
        self.assertEqual(maintainer.failure_class([], logs), maintainer.JUDGEMENT)

    def test_a_red_gate_with_exit_124_is_no_budget_kill(self) -> None:
        log = "FAILED TARGETS: lint-python\nmake: *** [test] Error 124\n"
        self.assertEqual(maintainer.failure_class([], [log]), maintainer.JUDGEMENT)

    def test_no_evidence_takes_the_forward_branch(self) -> None:
        self.assertEqual(maintainer._route_class({})["C1"], maintainer.JUDGEMENT)


class TestMaintainerDecisions(unittest.TestCase):
    def test_predict_keeps_the_matrix_line(self) -> None:
        state = maintainer._predict({"resolver_output": "web-app-gitea#0,2 svc-x"})
        self.assertEqual(state["matrix_line"], f"{MATRIX_LABEL} 3")

    def test_a_review_of_an_older_head_is_not_yet_read(self) -> None:
        older = maintainer._review_read({"pushed_sha": "b2", "review_sha": "a1"})
        self.assertEqual(older["D18"], "⏳ not yet")
        missing = maintainer._review_read({"pushed_sha": "b2"})
        self.assertEqual(missing["D18"], "⏳ not yet")
        current = maintainer._review_read({"pushed_sha": "b2", "review_sha": "b2"})
        self.assertEqual(current["D18"], "✅ read")
        self.assertEqual(maintainer._review_read({})["D18"], "✅ read")

    def test_gate_decision_reads_the_table(self) -> None:
        red = maintainer._gate_verdict({"gate_output": "FAILED TARGETS: lint-python"})
        self.assertEqual(red["D6"], "❌ red")
        green = maintainer._gate_verdict({"gate_output": "FAILED TARGETS:\n"})
        self.assertEqual(green["D6"], "✅ green")

    def test_number_decision_blocks_unbacked(self) -> None:
        state = maintainer._numbers_verdict(
            {"pr_text": "fixed 5 bugs", "evidence": "0 bugs"}
        )
        self.assertEqual(state["D10"], "❌ no")
        self.assertEqual(state["unbacked_numbers"], ["5"])

    def test_change_ran_decision_detects_silence(self) -> None:
        silent = maintainer._change_ran_verdict(
            {"ci_log": "- spec [skipped]", "change_marker": "spec"}
        )
        self.assertEqual(silent["D13"], "❌ no")
        ran = maintainer._change_ran_verdict(
            {"ci_log": "✓ spec passed", "change_marker": "spec"}
        )
        self.assertEqual(ran["D13"], "✅ yes")

    @unittest.skipUnless(
        _HAVE_LANGGRAPH,
        "langgraph ships in the orchestrator image, not the sandbox venv",
    )
    def test_stub_run_reaches_a_terminal(self) -> None:
        result = maintainer.build().invoke({})
        self.assertEqual(result["D13"], "❌ no")


if __name__ == "__main__":
    unittest.main()
