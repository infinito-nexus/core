"""Unit test: ``python -m agents.routines decide`` runs one decision step of a
routine over a JSON state file, refuses a missing state file without
``--init`` and a mistyped state key by name, lists the state keys in its help,
reads the run's log, exit status and poll, writes the polled run step and the
state back without the raw log, records the ledger and prints the label."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from agents.routines.__main__ import main
from agents.routines.iterate import (
    ENDED,
    GREEN,
    HUNG,
    NEW,
    NO_RUN_STEP,
    REPEATED,
    STATE_KEYS,
)
from agents.routines.tools.watchdog import SILENCE_SECONDS
from tests.unit.python.agents.routines import tools as ansible
from tests.unit.python.agents.routines import written_text

_FAILED = 'fatal: [localhost]: FAILED! => {"msg": "port 3000 never opened"}\n'


def _decide(*argv: str) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["decide", *argv])
    return code, out.getvalue().strip(), err.getvalue().strip()


def _silent_log(tmp: str, text: str) -> Path:
    log = Path(tmp) / "run.log"
    log.write_text(text, encoding="utf-8")
    old = log.stat().st_mtime - SILENCE_SECONDS - 60
    os.utime(log, (old, old))
    return log


class TestDecideCommand(unittest.TestCase):
    def test_signature_twice_repeats_through_the_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            log = Path(tmp) / "run.log"
            log.write_text(_FAILED, encoding="utf-8")
            args = ("iterate_compose", "signature", "--state", str(state))
            self.assertEqual(_decide(*args, "--init", "--log", str(log))[:2], (0, NEW))
            self.assertEqual(_decide(*args, "--log", str(log))[:2], (0, REPEATED))

    def test_the_state_keeps_no_raw_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            log = Path(tmp) / "run.log"
            log.write_text(_FAILED, encoding="utf-8")
            _decide(
                "iterate_compose",
                "signature",
                "--state",
                str(state),
                "--init",
                "--log",
                str(log),
            )
            saved = json.loads(written_text(state))
        self.assertNotIn("run_log", saved)
        self.assertNotIn("port 3000", json.dumps(saved))

    def test_the_ledger_gets_one_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.jsonl"
            state = Path(tmp) / "state.json"
            state.write_text(json.dumps({"ledger": str(ledger)}), encoding="utf-8")
            _decide("iterate_swarm", "relevant_delta", "--state", str(state))
            (line,) = written_text(ledger).splitlines()
        self.assertEqual(json.loads(line)["step"], "relevant_delta")

    def test_a_missing_state_file_is_refused_without_init(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "stat.json"
            code, _, err = _decide(
                "iterate_swarm", "relevant_delta", "--state", str(state)
            )
            self.assertEqual(code, 1)
            self.assertIn("--init", err)
            self.assertFalse(state.exists())

    def test_a_mistyped_key_is_refused_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            state.write_text(json.dumps({"roles": "web-app-gitea"}), encoding="utf-8")
            code, _, err = _decide(
                "iterate_swarm", "relevant_delta", "--state", str(state)
            )
        self.assertEqual(code, 1)
        self.assertIn("'roles'", err)

    def test_a_state_that_is_a_list_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            state.write_text("[]", encoding="utf-8")
            code, _, err = _decide(
                "iterate_swarm", "relevant_delta", "--state", str(state)
            )
        self.assertEqual(code, 1)
        self.assertIn("JSON object", err)

    def test_the_help_lists_the_state_keys(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.suppress(SystemExit):
            main(["decide", "-h"])
        for key in STATE_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, out.getvalue())

    def test_a_silent_log_while_running_is_hung(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            log = _silent_log(tmp, "TASK [web-app-gitea : Pull images]\n")
            result = _decide(
                "iterate_compose",
                "hung",
                "--state",
                str(state),
                "--init",
                "--log",
                str(log),
                "--running",
                "redeploy",
            )
            saved = json.loads(written_text(state))
        self.assertEqual(result[:2], (0, HUNG))
        self.assertEqual(saved["running_step"], "redeploy")

    def test_a_run_with_the_wrapper_exit_line_is_ended_while_polled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            log = _silent_log(tmp, ansible.red_run(ansible.CHANGED, "x", 1, 0))
            result = _decide(
                "iterate_compose",
                "hung",
                "--state",
                str(state),
                "--init",
                "--log",
                str(log),
                "--running",
                "redeploy",
            )
        self.assertEqual(result[:2], (0, ENDED))

    def test_a_run_that_wrote_its_exit_status_is_ended(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            log = _silent_log(tmp, "make test\n")
            exit_file = Path(tmp) / "exit"
            exit_file.write_text("2\n", encoding="utf-8")
            result = _decide(
                "iterate_compose",
                "hung",
                "--state",
                str(state),
                "--init",
                "--log",
                str(log),
                "--running",
                "gate",
                "--exit-file",
                str(exit_file),
            )
        self.assertEqual(result[:2], (0, ENDED))

    def test_an_unknown_running_step_is_refused(self) -> None:
        for step in ("x", "inspect"):
            with self.subTest(step=step), tempfile.TemporaryDirectory() as tmp:
                state = Path(tmp) / "state.json"
                code = _decide(
                    "iterate_compose",
                    "hung",
                    "--state",
                    str(state),
                    "--init",
                    "--running",
                    step,
                )[0]
                self.assertEqual(code, 1)

    def test_a_green_deploy_polled_while_running_is_green(self) -> None:
        for age in (5, 1000):
            with self.subTest(age=age), tempfile.TemporaryDirectory() as tmp:
                state = Path(tmp) / "state.json"
                log = Path(tmp) / "run.log"
                log.write_text(ansible.green_run(), encoding="utf-8")
                stamp = log.stat().st_mtime - age
                os.utime(log, (stamp, stamp))
                result = _decide(
                    "iterate_compose",
                    "hung",
                    "--state",
                    str(state),
                    "--init",
                    "--log",
                    str(log),
                    "--running",
                    "redeploy",
                )
                self.assertEqual(result[:2], (0, GREEN))

    def test_a_missing_exit_file_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            missing = str(Path(tmp) / "no-such.exit")
            result = _decide(
                "iterate_compose",
                "hung",
                "--state",
                str(state),
                "--init",
                "--running",
                "sync",
                "--exit-file",
                missing,
            )
        self.assertIn(missing, result[2])

    def test_a_missing_log_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            code, _, err = _decide(
                "iterate_compose",
                "reached",
                "--state",
                str(state),
                "--init",
                "--log",
                str(Path(tmp) / "no-such.log"),
            )
        self.assertEqual(code, 1)
        self.assertIn("no-such.log", err)

    def test_a_gone_process_ends_the_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            log = _silent_log(tmp, "TASK [web-app-gitea : Pull images]\n")
            result = _decide(
                "iterate_compose",
                "hung",
                "--state",
                str(state),
                "--init",
                "--log",
                str(log),
                "--running",
                "redeploy",
                "--pid",
                "0",
            )
        self.assertEqual(result[:2], (0, ENDED))

    def test_wait_without_a_running_step_names_the_poll_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            result = _decide("iterate_compose", "wait", "--state", str(state), "--init")
        self.assertEqual(result[:2], (0, NO_RUN_STEP))
        self.assertIn("--running <run step>", result[1])

    def test_a_recap_between_two_plays_is_no_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            log = _silent_log(
                tmp, ansible.rescued_recap() + "\nPLAY [Deploy the applications] ****\n"
            )
            result = _decide(
                "iterate_compose",
                "hung",
                "--state",
                str(state),
                "--init",
                "--log",
                str(log),
                "--running",
                "redeploy",
            )
        self.assertEqual(result[:2], (0, HUNG))

    def test_a_step_that_is_no_decision_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            self.assertEqual(
                _decide("iterate_compose", "redeploy", "--state", str(state), "--init")[
                    0
                ],
                1,
            )
            self.assertFalse(state.exists())


if __name__ == "__main__":
    unittest.main()
