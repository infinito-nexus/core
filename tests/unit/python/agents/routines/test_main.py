"""Unit test: ``python -m agents.routines decide`` runs one decision step of a
routine over a JSON state file, refuses a missing state file without
``--init`` and a mistyped state key by name, lists the state keys in its help,
reads the run's log, exit status and poll, writes the polled run step and the
state back without the raw log, records the ledger with the evidence source
and prints the label. ``run`` records and shows an operator override, pauses an
``ask`` step on the owner's answer, and a failed log write kills the run's
whole process group."""

from __future__ import annotations

import contextlib
import io
import json
import os
import signal
import sys
import tempfile
import time
import unittest
import unittest.mock as mock
from dataclasses import dataclass
from pathlib import Path

from agents.routines import load
from agents.routines.__main__ import (
    ABORTED_EXIT,
    LOG_FAILED_EXIT,
    ask_owner,
    main,
    supervise,
)
from agents.routines.contract import asked
from agents.routines.iterate import (
    ALIVE,
    ENDED,
    GREEN,
    HUNG,
    NEW,
    NO_RUN_STEP,
    REPEATED,
    STATE_KEYS,
)
from agents.routines.tools.watchdog import BUSY_CORES, SILENCE_SECONDS
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

    def test_the_ledger_names_the_evidence_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.jsonl"
            state = Path(tmp) / "state.json"
            state.write_text(json.dumps({"ledger": str(ledger)}), encoding="utf-8")
            log = Path(tmp) / "run.log"
            log.write_text(_FAILED, encoding="utf-8")
            _decide(
                "iterate_compose", "signature", "--state", str(state), "--log", str(log)
            )
            (line,) = written_text(ledger).splitlines()
            saved = json.loads(written_text(state))
        self.assertEqual(json.loads(line)["evidence_source"], f"log:{log}")
        self.assertNotIn("evidence_source", saved)


def _stack_cgroup(tmp: str, usage_usec: int) -> Path:
    root = Path(tmp) / "docker-stack.scope"
    root.mkdir(exist_ok=True)
    (root / "cpu.stat").write_text(f"usage_usec {usage_usec}\n", encoding="utf-8")
    return root


class TestDecideStackCgroup(unittest.TestCase):
    def _baseline(self, tmp: str, usage_usec: int, seconds_ago: float) -> None:
        (Path(tmp) / "state.json").write_text(
            json.dumps(
                {
                    "ledger": str(Path(tmp) / "ledger.jsonl"),
                    "last_stack_cpu_usec": [usage_usec],
                    "last_polled_at": time.time() - seconds_ago,
                }
            ),
            encoding="utf-8",
        )

    def _poll(self, tmp: str, cgroup: Path) -> tuple[str, str, dict]:
        state = Path(tmp) / "state.json"
        log = _silent_log(tmp, "TASK [web-app-gitea : Build images]\n")
        code, out, err = _decide(
            "iterate_compose",
            "hung",
            "--state",
            str(state),
            "--init",
            "--log",
            str(log),
            "--running",
            "redeploy",
            "--cgroup",
            str(cgroup),
        )
        self.assertEqual(code, 0)
        return out, err, json.loads(written_text(state))

    def test_a_silent_run_on_a_working_stack_is_alive(self) -> None:
        working = int(2 * BUSY_CORES * 60 * 1_000_000)
        with tempfile.TemporaryDirectory() as tmp:
            self._baseline(tmp, 0, 60)
            out, _, saved = self._poll(tmp, _stack_cgroup(tmp, working))
        self.assertEqual(out, ALIVE)
        self.assertEqual(saved["last_stack_cpu_usec"], [working])
        self.assertNotIn("stack_cpu_usec", saved)

    def test_a_silent_run_on_a_resting_stack_is_hung(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._baseline(tmp, 0, 60)
            out, _, _ = self._poll(tmp, _stack_cgroup(tmp, int(0.32 * 60 * 1_000_000)))
        self.assertEqual(out, HUNG)

    def test_the_first_poll_of_a_stack_records_its_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out, _, saved = self._poll(tmp, _stack_cgroup(tmp, 7))
        self.assertEqual(out, ALIVE)
        self.assertEqual(saved["last_stack_cpu_usec"], [7])
        self.assertIn("last_polled_at", saved)

    def test_a_gone_stack_cgroup_is_reported_and_proves_no_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._baseline(tmp, 0, 60)
            out, err, _ = self._poll(tmp, Path(tmp) / "gone.scope")
        self.assertEqual(out, HUNG)
        self.assertIn("gone.scope", err)

    def test_the_ledger_names_the_stack_cgroup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._baseline(tmp, 0, 60)
            cgroup = _stack_cgroup(tmp, 0)
            self._poll(tmp, cgroup)
            (line,) = written_text(Path(tmp) / "ledger.jsonl").splitlines()
        record = json.loads(line)
        self.assertIn(f"cgroup:{cgroup}", record["evidence_source"])
        self.assertFalse(record["inputs"]["stack_busy"])


@dataclass(frozen=True)
class _StubChannel:
    name: str = "stub"
    remote: str = ""
    credential: str = ""

    def envelope(self, recipient: str, text: str) -> dict:
        return {"to": recipient, "text": text}


_SEEN: dict = {}


class _Graph:
    """Runs a routine's ask steps in order, as the compiled graph does."""

    def __init__(self, name: str, steps: list, approve) -> None:
        self._nodes = [
            asked(step, lambda state: state, approve)
            for step in steps
            if step.kind == "ask"
        ]

    def invoke(self, state: dict) -> dict:
        _SEEN.clear()
        _SEEN.update(state)
        for node in self._nodes:
            state = node(state)
        return state


def _run(*argv: str, stdin: str = "") -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with (
        mock.patch("agents.routines.__main__.build", _Graph),
        mock.patch("sys.stdin", io.StringIO(stdin)),
        contextlib.redirect_stdout(out),
        contextlib.redirect_stderr(err),
    ):
        code = main(["run", *argv])
    return code, out.getvalue().strip(), err.getvalue().strip()


class TestOverride(unittest.TestCase):
    def test_an_override_is_handed_on_recorded_and_shown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.jsonl"
            code, out, _ = _run(
                "translate", "--override", "mode=compose-only", "--ledger", str(ledger)
            )
            (line,) = written_text(ledger).splitlines()
        record = json.loads(line)
        self.assertEqual(code, 0)
        self.assertEqual(_SEEN["overrides"], {"mode": "compose-only"})
        self.assertEqual(
            (record["step"], record["inputs"], record["outcome"]),
            ("overrides", {"mode": "compose-only"}, "accepted"),
        )
        self.assertEqual(out, "translate: done; overrides: mode=compose-only")

    def test_an_override_without_a_value_is_refused(self) -> None:
        code, _, err = _run("translate", "--override", "compose-only")
        self.assertEqual(code, 1)
        self.assertIn("'compose-only'", err)


class TestAsk(unittest.TestCase):
    def _approve(self, answer: str, sent: list):
        return ask_owner(_StubChannel(), "kevin", sent.append, lambda: answer)

    def test_the_owner_gets_the_request_and_approve_resumes(self) -> None:
        sent: list = []
        step = next(s for s in _hacker_steps() if s.id == "H1")
        ran: list = []
        node = asked(
            step,
            lambda state: ran.append(state) or state,
            self._approve("approve\n", sent),
        )
        state = node({})
        self.assertEqual(sent, [{"to": "kevin", "text": f"H1: {step.label}"}])
        self.assertEqual(state["H1"], step.branches[0][0])
        self.assertEqual(len(ran), 1)

    def test_reject_and_no_answer_abort_the_run(self) -> None:
        for answer in ("reject\n", ""):
            with self.subTest(answer=answer):
                code, out, _ = _run(
                    "hacker_scan",
                    "--owner",
                    "kevin",
                    "--homeserver",
                    "hs.example",
                    stdin=answer,
                )
                self.assertEqual(code, ABORTED_EXIT)
                self.assertEqual(out.splitlines()[-1], "hacker_scan: aborted at H1")

    def test_approve_on_stdin_resumes_the_run(self) -> None:
        code, out, _ = _run(
            "hacker_scan",
            "--owner",
            "kevin",
            "--homeserver",
            "hs.example",
            stdin="approve\n",
        )
        request = json.loads(out.splitlines()[0])["approval_request"]
        self.assertEqual(code, 0)
        self.assertIn("H1", json.dumps(request))
        self.assertEqual(out.splitlines()[-1], "hacker_scan: done")

    def test_without_an_owner_an_ask_aborts(self) -> None:
        code, _, err = _run("hacker_scan")
        self.assertEqual(code, ABORTED_EXIT)
        self.assertIn("'H1'", err)


def _hacker_steps() -> list:
    return load("hacker_scan").STEPS


_FAMILY = """
import os, subprocess, sys, time
grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
with open(sys.argv[1], "w") as handle:
    handle.write(f"{os.getpid()} {grandchild.pid}")
print("started", flush=True)
time.sleep(5)
"""


def _alive(pid: int) -> bool:
    try:
        with Path(f"/proc/{pid}/stat").open(encoding="utf-8") as handle:
            stat = handle.read()
    except (FileNotFoundError, ProcessLookupError):
        return False
    return stat.rsplit(")", 1)[1].split()[0] != "Z"


class TestLogWrite(unittest.TestCase):
    def test_a_failed_log_write_aborts_and_leaves_no_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pids = Path(tmp) / "pids"
            with contextlib.redirect_stderr(io.StringIO()) as err:
                code = supervise(
                    [sys.executable, "-c", _FAMILY, str(pids)], Path("/dev/full")
                )
            family = [int(pid) for pid in written_text(pids).split()]
        try:
            self.assertEqual(code, LOG_FAILED_EXIT)
            self.assertIn("/dev/full", err.getvalue())
            deadline = time.monotonic() + 5
            while any(_alive(pid) for pid in family) and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertEqual([pid for pid in family if _alive(pid)], [])
        finally:
            for pid in family:
                with contextlib.suppress(ProcessLookupError):
                    os.kill(pid, signal.SIGKILL)

    def test_the_output_reaches_the_log_and_the_status_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "run.log"
            with contextlib.redirect_stdout(io.StringIO()):
                code = supervise(
                    [sys.executable, "-c", "print('hello'); raise SystemExit(5)"], log
                )
            self.assertEqual(code, 5)
            self.assertEqual(written_text(log), "hello\n")


if __name__ == "__main__":
    unittest.main()
