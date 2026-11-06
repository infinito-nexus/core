"""Unit test: the contract's decision ledger appends one JSON record per decision
with its step, inputs, outcome and timestamp, creates its directory, writes a
set as a sorted list, refuses a relative path, writes nothing without a path, and
hands the outcome to the router under the step id."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from agents.routines.contract import LEDGER_KEY, append_record, decide
from tests.unit.python.agents.routines import written_text


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


if __name__ == "__main__":
    unittest.main()
