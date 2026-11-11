"""Unit test: the contract's decision ledger appends one JSON record per decision
with its step, inputs, outcome and timestamp, creates its directory, writes a
set as a sorted list, refuses a relative path, writes nothing without a path, and
hands the outcome to the router under the step id."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from agents.routines.contract import LEDGER_KEY, append_record, decide, gated
from tests.unit.python.agents.routines import written_text
from utils.orchestrator.locks import GATE, hold


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in written_text(path).splitlines()]


class TestLedger(unittest.TestCase):
    def test_record_carries_step_inputs_outcome_and_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.jsonl"
            append_record(str(path), "hung", {"polled_at": 1.0}, "🧊 hung")
            (record,) = _records(path)
        self.assertEqual(record["step"], "hung")
        self.assertEqual(record["inputs"], {"polled_at": 1.0})
        self.assertEqual(record["outcome"], "🧊 hung")
        self.assertIsNotNone(datetime.fromisoformat(record["timestamp"]).tzinfo)

    def test_each_decision_appends_one_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.jsonl"
            append_record(str(path), "reached", {}, "🎯 reached")
            append_record(str(path), "signature", {}, "🆕 new")
            steps = [record["step"] for record in _records(path)]
        self.assertEqual(steps, ["reached", "signature"])

    def test_a_missing_directory_is_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "loop" / "ledger.jsonl"
            append_record(str(path), "hung", {}, "▶️ ended")
            self.assertEqual(len(_records(path)), 1)

    def test_a_set_input_is_written_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.jsonl"
            append_record(str(path), "relevant_delta", {"roles": {"b", "a"}}, "x")
            (record,) = _records(path)
        self.assertEqual(record["inputs"]["roles"], ["a", "b"])

    def test_a_relative_path_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            append_record("ledger.jsonl", "hung", {}, "▶️ ended")

    def test_no_path_opens_no_file(self) -> None:
        with mock.patch.object(Path, "open") as opened:
            record = append_record("", "hung", {}, "▶️ ended")
        opened.assert_not_called()
        self.assertEqual(record["outcome"], "▶️ ended")

    def test_decide_writes_the_branch_under_the_step_id(self) -> None:
        state = decide({}, "relevant_delta", {}, "⏸️ unchanged")
        self.assertEqual(state["relevant_delta"], "⏸️ unchanged")

    def test_decide_records_in_the_ledger_the_state_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.jsonl"
            decide({LEDGER_KEY: str(path)}, "signature", {"red_runs": 1}, "🆕 new")
            (record,) = _records(path)
        self.assertEqual(record["inputs"], {"red_runs": 1})


class TestGateBeforeEveryStep(unittest.TestCase):
    """Each node reads the machine's gate lock first and waits while it is held."""

    def test_a_step_started_under_the_gate_lock_waits_for_its_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_dir = Path(tmp)
            held = threading.Event()
            release = threading.Event()

            def gate() -> None:
                with hold(lock_dir, GATE):
                    held.set()
                    release.wait(5)

            thread = threading.Thread(target=gate)
            thread.start()
            held.wait(5)
            order: list[str] = []

            def sleep(_seconds: float) -> None:
                order.append("waited")
                release.set()
                thread.join(5)

            def step(state: dict) -> dict:
                order.append("ran")
                return {**state, "done": True}

            self.assertEqual(gated(step, lock_dir, sleep)({}), {"done": True})
        self.assertEqual(order, ["waited", "ran"])

    def test_a_free_gate_runs_the_step_at_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            node = gated(lambda state: state, Path(tmp), self.fail)
            self.assertEqual(node({"a": 1}), {"a": 1})


if __name__ == "__main__":
    unittest.main()
