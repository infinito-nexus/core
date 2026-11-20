"""Unit test: the shared decision steps of the iterate routines decide on their
evidence and record every decision in the ledger, and every iterate routine
puts the relevant-delta check before its rerun and the red chain (watchdog,
reached check, signature stop rule) after each red or still-running run."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agents.routines import iterate
from agents.routines.iterate import (
    ALIVE,
    CHANGED,
    DECIDE,
    ENDED,
    GREEN,
    HUNG,
    NEW,
    NO_RUN_STEP,
    PRE_CODE,
    REACHED,
    REPEATED,
    RUNNING,
    UNCHANGED,
    compose,
    playwright,
    roundtrip,
    runner,
    swarm,
    workflow,
)
from agents.routines.tools.watchdog import BUSY_CORES, SILENCE_SECONDS
from tests.unit.python.agents.routines import tools as ansible
from tests.unit.python.agents.routines import written_text
from tests.unit.python.agents.routines.iterate import branch_map, walk
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

_ROLE = "web-app-gitea"
_RED = "❌ red"
_SHARED = "group_vars/all/00_general.yml"
_RETRY = "FAILED - RETRYING: [localhost]: Wait for docker daemon (60 retries left)."
_FAILED = 'fatal: [localhost]: FAILED! => {"msg": "port 3000 never opened"}'
_ROLE_LOG = f"TASK [{_ROLE} : Wait for the port] ****\n{_FAILED}\n"
_PROVIDER_LOG = f"TASK [svc-db-postgres : Start] ****\n{_FAILED}\n"
_RETRY_LOG = (
    f"TASK [sys-svc-docker : Wait for docker daemon] ****\n{_RETRY}\n"
    f"ok: [localhost]\n{_ROLE_LOG}"
)
_MARKER = f"TASK [{_ROLE} :"
_ROUTINES = {
    "compose": {
        "module": compose,
        "name": "iterate_compose",
        "red_runs": ("sync", "rebuild", "redeploy", "gate"),
        "reproduction": "baseline",
        "into_delta": "verify",
        "delta": {CHANGED: "scope", UNCHANGED: "inspect"},
        "runs_tests": True,
        "verdict": "inspect",
        "terminal": "done",
        "red_state": {"redeploy": _RED},
    },
    "swarm": {
        "module": swarm,
        "name": "iterate_swarm",
        "red_runs": ("sync", "rebuild"),
        "reproduction": "deploy",
        "into_delta": "fix",
        "delta": {CHANGED: "sync", UNCHANGED: "inspect"},
        "runs_tests": False,
        "verdict": "deploy",
        "terminal": "done",
        "red_state": {"rebuild": _RED},
    },
    "playwright": {
        "module": playwright,
        "name": "iterate_playwright",
        "red_runs": ("rerun", "baseline"),
        "reproduction": "",
        "into_delta": "edit",
        "delta": {CHANGED: "rerun", UNCHANGED: "edit"},
        "runs_tests": False,
        "verdict": "inspect",
        "terminal": "done",
        "red_state": {"rerun": _RED, "inspect": _RED},
    },
    "roundtrip": {
        "module": roundtrip,
        "name": "iterate_roundtrip",
        "red_runs": ("resume",),
        "reproduction": "sweep",
        "into_delta": "fix",
        "delta": {CHANGED: "resume", UNCHANGED: "triage"},
        "runs_tests": False,
        "verdict": "triage",
        "terminal": "confirm",
        "red_state": {"sweep": _RED, "resume": _RED},
    },
    "workflow": {
        "module": workflow,
        "name": "iterate_workflow",
        "red_runs": ("rerun",),
        "reproduction": "run",
        "into_delta": "inspect",
        "delta": {CHANGED: "rerun", UNCHANGED: "inspect"},
        "runs_tests": True,
        "verdict": "inspect",
        "terminal": "ci",
        "red_state": {"run": _RED, "rerun": _RED},
    },
    "runner": {
        "module": runner,
        "name": "iterate_runner",
        "red_runs": ("deploy",),
        "reproduction": "",
        "into_delta": "test",
        "delta": {CHANGED: "deploy", UNCHANGED: "edit"},
        "runs_tests": False,
        "verdict": "inspect",
        "terminal": "done",
        "red_state": {"deploy": _RED, "inspect": _RED},
    },
}


def _red_walk(case: dict, extra: dict) -> tuple[list[str], dict]:
    state = {**case["red_state"], "changed_paths": [_SHARED], **extra}
    return walk(case["module"].STEPS, state)


def _step(steps: list, step_id: str):
    (found,) = [step for step in steps if step.id == step_id]
    return found


class TestRelevantDelta(unittest.TestCase):
    def _decide(self, runs_tests: bool, **state) -> str:
        result = iterate._relevant_delta({"role": _ROLE, **state}, runs_tests)
        return result["relevant_delta"]

    def test_no_evidence_counts_as_changed(self) -> None:
        self.assertEqual(iterate._relevant_delta({}, False)["relevant_delta"], CHANGED)

    def test_an_empty_delta_skips_the_rerun(self) -> None:
        self.assertEqual(self._decide(False, changed_paths=[]), UNCHANGED)
        self.assertEqual(self._decide(True, changed_paths=[]), UNCHANGED)

    def test_docs_and_tests_only_skip_a_deploy_only_rerun(self) -> None:
        paths = [
            "docs/contributing/actions/deploy.md",
            f"tests/unit/python/roles/{_ROLE}/x.py",
        ]
        self.assertEqual(self._decide(False, changed_paths=paths), UNCHANGED)

    def test_a_tests_only_fix_reruns_a_run_that_runs_the_tests(self) -> None:
        paths = [f"tests/unit/python/roles/{_ROLE}/test_x.py"]
        self.assertEqual(self._decide(True, changed_paths=paths), CHANGED)

    def test_the_role_file_counts(self) -> None:
        own = f"roles/{_ROLE}/{ROLE_FILE_TASKS_MAIN}"
        self.assertEqual(self._decide(False, changed_paths=[own]), CHANGED)

    def test_another_role_counts_only_when_the_resolver_lists_the_role(self) -> None:
        other = [f"roles/svc-db-postgres/{ROLE_FILE_TASKS_MAIN}"]
        self.assertEqual(
            self._decide(False, changed_paths=other, delta_affected="svc-db-postgres"),
            UNCHANGED,
        )
        self.assertEqual(
            self._decide(
                False, changed_paths=other, delta_affected=f"svc-db-postgres {_ROLE}"
            ),
            CHANGED,
        )

    def test_a_second_role_under_test_counts(self) -> None:
        second = [f"roles/web-app-nextcloud/{ROLE_FILE_TASKS_MAIN}"]
        self.assertEqual(
            self._decide(
                False,
                roles=["web-app-nextcloud#1"],
                changed_paths=second,
                delta_affected="web-app-nextcloud",
            ),
            CHANGED,
        )

    def test_no_role_under_test_counts_as_changed(self) -> None:
        state = {
            "apps_order": ["web-app-a", "web-app-b"],
            "changed_paths": [f"roles/web-app-b/{ROLE_FILE_TASKS_MAIN}"],
            "delta_affected": "web-app-b",
        }
        self.assertEqual(
            iterate._relevant_delta(state, False)["relevant_delta"], CHANGED
        )

    def test_new_run_arguments_count_as_changed(self) -> None:
        self.assertEqual(
            self._decide(
                False, changed_paths=[], run_args="variant=1", last_run_args="variant=0"
            ),
            CHANGED,
        )

    def test_a_set_of_paths_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.jsonl"
            iterate._relevant_delta(
                {"ledger": str(ledger), "role": _ROLE, "changed_paths": {_SHARED}},
                False,
            )
            (line,) = written_text(ledger).splitlines()
        self.assertEqual(json.loads(line)["inputs"]["changed_paths"], [_SHARED])

    def test_the_label_diffs_against_a_tree_snapshot_not_a_commit(self) -> None:
        label = iterate.relevant_delta_step("iterate_x", "a", "b", False).label
        self.assertIn("GIT_INDEX_FILE=<tmp index> git add -A", label)
        self.assertIn("GIT_INDEX_FILE=<tmp index> git write-tree", label)
        self.assertIn(
            "git diff --name-only --no-renames <last_run_tree> <fresh tree>", label
        )
        self.assertNotIn("stash", label)
        self.assertNotIn("last_run_sha", label)
        self.assertIn(f"{DECIDE} iterate_x relevant_delta --state <state.json>", label)

    def test_the_ledger_records_the_tree_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.jsonl"
            iterate._relevant_delta(
                {"ledger": str(ledger), "changed_paths": [], "last_run_tree": "4b825d"},
                False,
            )
            (line,) = written_text(ledger).splitlines()
        self.assertEqual(json.loads(line)["inputs"]["last_run_tree"], "4b825d")


class TestHung(unittest.TestCase):
    def test_an_ended_run_is_not_hung(self) -> None:
        self.assertEqual(iterate._hung({"output_timestamps": [1.0]})["hung"], ENDED)

    def test_a_poll_past_the_silence_is_hung(self) -> None:
        state = {"output_timestamps": [100.0], "polled_at": 100.0 + SILENCE_SECONDS + 1}
        self.assertEqual(iterate._hung(state)["hung"], HUNG)

    def test_a_poll_within_the_silence_keeps_waiting(self) -> None:
        state = {"output_timestamps": [100.0], "polled_at": 100.0 + SILENCE_SECONDS}
        self.assertEqual(iterate._hung(state)["hung"], ALIVE)

    def test_a_run_silent_from_its_start_is_hung(self) -> None:
        state = {
            "output_timestamps": [],
            "started_at": 100.0,
            "polled_at": 100.0 + SILENCE_SECONDS + 1,
        }
        self.assertEqual(iterate._hung(state)["hung"], HUNG)

    def test_a_poll_of_a_run_with_the_wrapper_exit_line_is_ended(self) -> None:
        state = {
            "run_log": ansible.red_run(ansible.CHANGED, "x", 1, 0),
            "output_timestamps": [100.0],
            "polled_at": 100.0 + SILENCE_SECONDS + 1,
        }
        self.assertEqual(iterate._hung(state)["hung"], ENDED)

    def test_a_recap_between_two_plays_is_not_ended(self) -> None:
        between_plays = (
            ansible.passed(ansible.EARLIER, 1)
            + ansible.rescued_recap()
            + "\nPLAY [Deploy the applications] ****\n"
        )
        state = {"run_log": between_plays, "output_timestamps": [100.0]}
        self.assertEqual(iterate._hung({**state, "polled_at": 160.0})["hung"], ALIVE)
        self.assertEqual(
            iterate._hung({**state, "polled_at": 100.0 + SILENCE_SECONDS + 1})["hung"],
            HUNG,
        )

    def test_a_poll_of_a_run_that_wrote_its_exit_status_is_ended(self) -> None:
        state = {"exit_code": "2", "output_timestamps": [100.0], "polled_at": 200.0}
        self.assertEqual(iterate._hung(state)["hung"], ENDED)

    def test_the_label_names_the_silence(self) -> None:
        hung = _step(iterate.red_chain("iterate_x", "inspect", ("run",)), "hung")
        self.assertIn(f"{SILENCE_SECONDS:.0f} s", hung.label)
        self.assertNotIn("test-e2e-playwright", hung.label)
        self.assertNotIn("Playwright budget", hung.label)
        self.assertIn("--pid <run pid>", hung.label)

    def test_the_label_names_the_stack_cgroup(self) -> None:
        hung = _step(iterate.red_chain("iterate_x", "inspect", ("run",)), "hung")
        self.assertIn("[--cgroup <stack cgroup>]", hung.label)
        self.assertIn(f"{BUSY_CORES:g} core", hung.label)

    def test_the_label_names_the_running_and_the_ended_command(self) -> None:
        hung = _step(iterate.red_chain("iterate_x", "inspect", ("run",)), "hung")
        self.assertIn(
            "hung --state <state.json> --log <run log> --running <run step>", hung.label
        )
        self.assertIn("--exit-file <exit status file>", hung.label)
        self.assertIn("make Error line", hung.label)
        self.assertIn("not on a PLAY RECAP alone", hung.label)
        self.assertIn("exit status 0 is green", hung.label)

    def test_a_missing_ledger_directory_is_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "missing" / "ledger.jsonl"
            iterate._hung({"ledger": str(ledger)})
            self.assertTrue(ledger.is_file())


class TestGreenEnd(unittest.TestCase):
    def test_exit_status_zero_is_green_and_returns_to_the_run(self) -> None:
        state = iterate._hung(
            {
                "exit_code": "0",
                "running_step": "redeploy",
                "signatures": ["a"],
                "polled_at": 1.0,
            }
        )
        self.assertEqual(state["hung"], GREEN)
        self.assertEqual(state["redeploy"], "✅ green")
        self.assertEqual(state["signatures"], [])

    def test_the_deploy_closing_line_is_green(self) -> None:
        state = iterate._hung({"run_log": ansible.green_run(), "polled_at": 1.0})
        self.assertEqual(state["hung"], GREEN)

    def test_a_polled_run_that_ends_green_walks_on_to_done(self) -> None:
        state = {
            "redeploy": RUNNING,
            "running_step": "redeploy",
            "changed_paths": [_SHARED],
            "run_log": ansible.green_run(),
            "polled_at": 1.0,
        }
        visited, _ = walk(compose.STEPS, state)
        self.assertEqual(visited[-1], "done")
        self.assertNotIn("signature", visited)

    def test_a_signature_after_a_green_end_never_repeats(self) -> None:
        state = {"hung": GREEN, "signatures": ["a"], "run_log": "x"}
        first = iterate._signature(dict(state))
        second = iterate._signature({**first, "hung": GREEN})
        self.assertEqual((first["signature"], second["signature"]), (NEW, NEW))
        self.assertEqual(second["signatures"], [])


class TestBusyTree(unittest.TestCase):
    def test_a_silent_run_whose_tree_still_works_is_alive(self) -> None:
        state = {
            "output_timestamps": [100.0],
            "polled_at": 100.0 + SILENCE_SECONDS + 1,
            "process_ticks": 50,
            "last_process_ticks": 40,
        }
        result = iterate._hung(state)
        self.assertEqual(result["hung"], ALIVE)
        self.assertEqual(result["last_process_ticks"], 50)

    def test_a_silent_run_whose_tree_is_idle_is_hung(self) -> None:
        state = {
            "output_timestamps": [100.0],
            "polled_at": 100.0 + SILENCE_SECONDS + 1,
            "process_ticks": 40,
            "last_process_ticks": 40,
        }
        self.assertEqual(iterate._hung(state)["hung"], HUNG)


def _stack_poll(usage: list[float], silence: float) -> dict:
    """Return the state of a poll whose stack cgroups worked ``usage`` cores.

    Args:
        usage: the cores each stack cgroup used over the 60 s since the poll
            before.
        silence: the seconds since the run's last output line.
    """
    return {
        "output_timestamps": [100.0],
        "polled_at": 100.0 + silence,
        "last_polled_at": 40.0 + silence,
        "stack_cpu_usec": [int(cores * 60 * 1_000_000) for cores in usage],
        "last_stack_cpu_usec": [0] * len(usage),
    }


class TestBusyStack(unittest.TestCase):
    def test_a_silent_run_on_a_resting_stack_fires_after_the_silence(self) -> None:
        self.assertEqual(
            iterate._hung(_stack_poll([0.32], SILENCE_SECONDS))["hung"], ALIVE
        )
        self.assertEqual(
            iterate._hung(_stack_poll([0.32], SILENCE_SECONDS + 1))["hung"], HUNG
        )

    def test_a_silent_run_on_a_working_stack_does_not_fire(self) -> None:
        state = iterate._hung(_stack_poll([BUSY_CORES], 2 * SILENCE_SECONDS))
        self.assertEqual(state["hung"], ALIVE)
        self.assertEqual(state["last_stack_cpu_usec"], [int(BUSY_CORES * 60_000_000)])
        self.assertEqual(state["last_polled_at"], 100.0 + 2 * SILENCE_SECONDS)

    def test_a_swarm_whose_nodes_rest_together_above_one_core_fires(self) -> None:
        resting = [0.3, 0.3, 0.3, 0.3]
        self.assertGreater(sum(resting), BUSY_CORES)
        self.assertEqual(
            iterate._hung(_stack_poll(resting, SILENCE_SECONDS + 1))["hung"], HUNG
        )
        working = [0.3, BUSY_CORES, 0.3, 0.3]
        self.assertEqual(
            iterate._hung(_stack_poll(working, SILENCE_SECONDS + 1))["hung"], ALIVE
        )

    def test_a_heartbeat_run_on_a_resting_stack_does_not_fire(self) -> None:
        state = _stack_poll([0.0], SILENCE_SECONDS + 1)
        heartbeat = {**state, "output_timestamps": [state["polled_at"] - 10.0]}
        self.assertEqual(iterate._hung(heartbeat)["hung"], ALIVE)
        self.assertEqual(iterate._hung(state)["hung"], HUNG)

    def test_the_first_stack_poll_waits_for_a_baseline(self) -> None:
        first = {
            "output_timestamps": [100.0],
            "polled_at": 100.0 + SILENCE_SECONDS + 1,
            "stack_cpu_usec": [5],
        }
        state = iterate._hung(first)
        self.assertEqual(state["hung"], ALIVE)
        second = {
            **state,
            "polled_at": 160.0 + SILENCE_SECONDS + 1,
            "stack_cpu_usec": [5],
        }
        self.assertEqual(iterate._hung(second)["hung"], HUNG)

    def test_a_failed_recap_ends_the_run(self) -> None:
        log = (
            ansible.banner(ansible.CHANGED, 9)
            + ansible.failure("x", 1)
            + ansible.recap()
        )
        state = {"run_log": log, "output_timestamps": [1.0], "polled_at": 2.0}
        self.assertEqual(iterate._hung(state)["hung"], ENDED)

    def test_the_snapshot_index_must_not_exist_yet(self) -> None:
        label = iterate.relevant_delta_step("iterate_x", "a", "b", False).label
        self.assertIn("a path that does not exist yet", label)


class TestWait(unittest.TestCase):
    def test_wait_returns_to_the_polled_run(self) -> None:
        self.assertEqual(
            iterate._wait({"running_step": "gate"}, ("sync", "gate"))["wait"], "gate"
        )

    def test_wait_without_a_known_running_step_asks_for_a_new_poll(self) -> None:
        for state in ({}, {"running_step": "deploy"}):
            with self.subTest(state=state):
                outcome = iterate._wait(state, ("sync", "gate"))["wait"]
                self.assertEqual(outcome, NO_RUN_STEP)
                self.assertIn("--running <run step>", outcome)

    def test_a_graph_run_without_a_running_step_stops_at_the_poll(self) -> None:
        state = {
            "redeploy": RUNNING,
            "changed_paths": [_SHARED],
            "output_timestamps": [100.0],
            "polled_at": 160.0,
        }
        visited, _ = walk(compose.STEPS, state)
        self.assertEqual(visited[-2:], ["wait", "poll"])
        self.assertIn(
            "hung --state <state.json> --log <run log> --running <run step>",
            _step(compose.STEPS, "poll").label,
        )

    def test_the_label_names_its_decide_command(self) -> None:
        wait = _step(iterate.red_chain("iterate_x", "inspect", ("run",)), "wait")
        self.assertIn(f"{DECIDE} iterate_x wait --state <state.json>", wait.label)


class TestHalted(unittest.TestCase):
    def test_a_halted_run_is_judged_on_its_whole_log(self) -> None:
        state = {
            "run_log": "AssertionError: tolerated\nchanged test started\n",
            "change_marker": "changed test",
        }
        self.assertEqual(iterate._reached(dict(state))["reached"], PRE_CODE)
        self.assertEqual(iterate._reached({**state, "hung": HUNG})["reached"], REACHED)

    def test_a_rescued_fatal_before_the_change_is_no_pre_code(self) -> None:
        log = ansible.rescued(
            "svc-db-postgres : Migrate", "lock held"
        ) + ansible.hung_run(ansible.CHANGED, "Pulling layer 4 of 9", 0)
        state = {"run_log": log, "change_marker": ansible.MARKER}
        self.assertEqual(iterate._reached(state)["reached"], REACHED)

    def test_a_halted_run_signs_the_task_it_hangs_in(self) -> None:
        first = iterate._signature(
            {"hung": HUNG, "run_log": ansible.hung_run(ansible.CHANGED, "layer 4", 2)}
        )
        second = iterate._signature(
            {**first, "run_log": ansible.hung_run(ansible.CHANGED, "layer 7", 9)}
        )
        self.assertEqual(second["signature"], REPEATED)

    def test_the_halt_label_matches_the_code(self) -> None:
        halt = _step(iterate.red_chain("iterate_x", "inspect", ("run",)), "halt")
        self.assertIn("whole log", halt.label)
        self.assertIn("last TASK banner", halt.label)


class TestByHandLabels(unittest.TestCase):
    def test_the_compose_scope_names_its_decide_command(self) -> None:
        scope = _step(compose.STEPS, "scope")
        self.assertIn(
            f"{DECIDE} iterate_compose scope --state <state.json>", scope.label
        )

    def test_the_roundtrip_resume_says_it_runs_by_hand(self) -> None:
        self.assertIn("by hand", _step(roundtrip.STEPS, "resume").label)


class TestGraphStateIsChecked(unittest.TestCase):
    def test_every_decision_refuses_a_mistyped_state_by_name(self) -> None:
        decisions = {
            "relevant_delta": lambda state: iterate._relevant_delta(state, False),
            "hung": iterate._hung,
            "wait": lambda state: iterate._wait(state, ("gate",)),
            "reached": iterate._reached,
            "signature": iterate._signature,
            "scope": compose._scope,
        }
        for name, decision in decisions.items():
            with self.subTest(step=name), self.assertRaisesRegex(TypeError, "'roles'"):
                decision({"roles": _ROLE})


class TestCheckState(unittest.TestCase):
    def test_a_well_typed_state_passes(self) -> None:
        iterate.check_state(
            {"roles": [_ROLE], "started_at": 1, "signatures": ["a"], "run_args": [1]}
        )
        iterate.check_state({"changed_paths": {_SHARED}, "roles": (_ROLE,)})

    def test_a_wrong_type_is_refused_by_name(self) -> None:
        cases = {
            "roles": _ROLE,
            "role": [_ROLE],
            "changed_paths": "",
            "signatures": "abc",
            "started_at": "now",
            "output_timestamps": 5,
        }
        for key, value in cases.items():
            with self.subTest(key=key), self.assertRaisesRegex(TypeError, key):
                iterate.check_state({key: value})

    def test_a_state_that_is_no_object_is_refused(self) -> None:
        with self.assertRaisesRegex(TypeError, "JSON object"):
            iterate.check_state([])


class TestReached(unittest.TestCase):
    def _decide(self, **state) -> str:
        return iterate._reached(state)["reached"]

    def test_no_marker_counts_as_reached(self) -> None:
        self.assertEqual(self._decide(run_log=_PROVIDER_LOG), REACHED)

    def test_no_evidence_counts_as_reached(self) -> None:
        self.assertEqual(self._decide(change_marker=_MARKER), REACHED)

    def test_a_red_after_the_marker_is_reached(self) -> None:
        self.assertEqual(
            self._decide(run_log=_ROLE_LOG, change_marker=_MARKER), REACHED
        )

    def test_a_retry_before_the_marker_is_no_failure(self) -> None:
        self.assertEqual(
            self._decide(run_log=_RETRY_LOG, change_marker=_MARKER), REACHED
        )

    def test_a_red_before_the_marker_is_pre_code(self) -> None:
        self.assertEqual(
            self._decide(run_log=_PROVIDER_LOG, change_marker=_MARKER), PRE_CODE
        )

    def test_any_failed_junit_case_naming_the_marker_is_reached(self) -> None:
        junit = (
            '<testsuite><testcase name="other"><failure message="x"/></testcase>'
            '<testcase name="admin signs in"><failure message="y"/></testcase>'
            "</testsuite>"
        )
        self.assertEqual(
            self._decide(junit_xml=junit, change_marker="admin signs in"), REACHED
        )

    def test_a_passed_spec_after_an_earlier_failure_is_reached(self) -> None:
        log = "  ✗  a.spec.js:1:1 › other\n  ✓  b.spec.js:1:1 › changed test (1.0s)\n"
        self.assertEqual(
            self._decide(run_log=log, change_marker="changed test"), REACHED
        )


class TestSignature(unittest.TestCase):
    def test_the_first_red_is_new_and_kept(self) -> None:
        state = iterate._signature({"run_log": _ROLE_LOG})
        self.assertEqual(state["signature"], NEW)
        self.assertEqual(len(state["signatures"]), 1)

    def test_the_same_failure_twice_in_a_row_repeats(self) -> None:
        first = iterate._signature({"run_log": f"2026-11-06T01:00:00Z {_FAILED}"})
        second = iterate._signature(
            {**first, "run_log": f"2026-11-06T02:30:00Z {_FAILED}"}
        )
        self.assertEqual(second["signature"], REPEATED)

    def test_a_different_failure_is_new(self) -> None:
        first = iterate._signature({"run_log": _ROLE_LOG})
        second = iterate._signature({**first, "run_log": "fatal: FAILED! other"})
        self.assertEqual(second["signature"], NEW)

    def test_two_reds_without_failure_text_repeat(self) -> None:
        first = iterate._signature({})
        self.assertEqual(first["signature"], NEW)
        self.assertEqual(iterate._signature(first)["signature"], REPEATED)

    def test_the_ledger_keeps_no_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.jsonl"
            state = iterate._signature({"ledger": str(ledger), "run_log": _ROLE_LOG})
            text = written_text(ledger)
        self.assertNotIn(state["signatures"][0], text)


class TestRedChain(unittest.TestCase):
    def test_branch_maps(self) -> None:
        steps = iterate.red_chain("iterate_x", "inspect", ("run", "rerun"))
        self.assertEqual(
            branch_map(steps, "hung"),
            {ENDED: "reached", HUNG: "halt", ALIVE: "wait", GREEN: "wait"},
        )
        self.assertEqual(
            branch_map(steps, "wait"),
            {"run": "run", "rerun": "rerun", NO_RUN_STEP: "poll"},
        )
        self.assertEqual(
            branch_map(steps, "reached"), {REACHED: "signature", PRE_CODE: "precode"}
        )
        self.assertEqual(
            branch_map(steps, "signature"), {NEW: "inspect", REPEATED: "escalate"}
        )

    def test_halt_rejoins_the_chain(self) -> None:
        steps = iterate.red_chain("iterate_x", "inspect", ("run",))
        self.assertEqual(_step(steps, "halt").nxt, "reached")

    def test_both_stops_are_terminals(self) -> None:
        kinds = {
            step.id: step.kind
            for step in iterate.red_chain("iterate_x", "inspect", ("run",))
        }
        self.assertEqual(kinds["precode"], "terminal")
        self.assertEqual(kinds["escalate"], "terminal")

    def test_every_decision_label_names_its_decide_command(self) -> None:
        for step in iterate.red_chain("iterate_x", "inspect", ("run",)):
            if step.kind == "decision" and step.id != "wait":
                with self.subTest(step=step.id):
                    self.assertIn(f"{DECIDE} iterate_x {step.id} --state", step.label)


class TestRoutineWiring(unittest.TestCase):
    def test_every_red_or_running_run_enters_the_watchdog(self) -> None:
        for name, case in _ROUTINES.items():
            for step_id in case["red_runs"]:
                with self.subTest(routine=name, step=step_id):
                    branches = branch_map(case["module"].STEPS, step_id)
                    self.assertEqual(branches.get(_RED), "hung")
                    self.assertEqual(branches.get(RUNNING), "hung")

    def test_wait_returns_to_every_run_of_the_chain(self) -> None:
        for name, case in _ROUTINES.items():
            with self.subTest(routine=name):
                self.assertEqual(
                    set(branch_map(case["module"].STEPS, "wait")),
                    {*case["red_runs"], NO_RUN_STEP},
                )

    def test_the_reproduction_run_stays_out_of_the_red_chain(self) -> None:
        for name, case in _ROUTINES.items():
            if not case["reproduction"]:
                continue
            with self.subTest(routine=name):
                step = _step(case["module"].STEPS, case["reproduction"])
                targets = {step.nxt} | {target for _, target in step.branches}
                self.assertNotIn("hung", targets)

    def test_the_relevant_delta_guards_the_rerun(self) -> None:
        for name, case in _ROUTINES.items():
            with self.subTest(routine=name):
                steps = case["module"].STEPS
                self.assertEqual(branch_map(steps, "relevant_delta"), case["delta"])
                self.assertEqual(_step(steps, case["into_delta"]).nxt, "relevant_delta")

    def test_a_tests_only_fix_follows_what_the_rerun_reads(self) -> None:
        state = {
            "role": _ROLE,
            "changed_paths": [f"tests/unit/python/roles/{_ROLE}/t.py"],
        }
        for name, case in _ROUTINES.items():
            with self.subTest(routine=name):
                delta = _step(case["module"].STEPS, "relevant_delta")
                expected = CHANGED if case["runs_tests"] else UNCHANGED
                self.assertEqual(delta.fn(dict(state))["relevant_delta"], expected)

    def test_labels_name_the_routine_decide_command(self) -> None:
        for name, case in _ROUTINES.items():
            with self.subTest(routine=name):
                for step_id in ("relevant_delta", "hung", "reached", "signature"):
                    self.assertIn(
                        f"{DECIDE} {case['name']} {step_id} --state",
                        _step(case["module"].STEPS, step_id).label,
                    )

    def test_a_new_red_continues_at_the_routine_verdict_step(self) -> None:
        for name, case in _ROUTINES.items():
            with self.subTest(routine=name):
                self.assertEqual(
                    branch_map(case["module"].STEPS, "signature"),
                    {NEW: case["verdict"], REPEATED: "escalate"},
                )

    def test_a_stub_run_reaches_the_forward_terminal(self) -> None:
        for name, case in _ROUTINES.items():
            with self.subTest(routine=name):
                visited, _ = walk(case["module"].STEPS, {})
                self.assertEqual(visited[-1], case["terminal"])

    def test_two_identical_reds_in_a_row_escalate(self) -> None:
        for name, case in _ROUTINES.items():
            with self.subTest(routine=name):
                visited, _ = _red_walk(case, {"run_log": _ROLE_LOG})
                self.assertEqual(visited[-1], "escalate")
                self.assertEqual(visited.count("signature"), 2)

    def test_two_reds_without_a_log_escalate(self) -> None:
        for name, case in _ROUTINES.items():
            with self.subTest(routine=name):
                visited, _ = _red_walk(case, {})
                self.assertEqual(visited[-1], "escalate")

    def test_two_different_fatals_behind_one_retry_do_not_escalate(self) -> None:
        other = _RETRY_LOG.replace("port 3000 never opened", "template error")
        earlier = iterate._signature({"run_log": other})["signatures"]
        for name, case in _ROUTINES.items():
            with self.subTest(routine=name):
                visited, _ = _red_walk(
                    case, {"run_log": _RETRY_LOG, "signatures": earlier}
                )
                first = visited.index("signature")
                self.assertEqual(visited[first + 1], case["verdict"])
                self.assertEqual(visited.count("signature"), 2)

    def test_a_red_before_the_change_stops_as_pre_code(self) -> None:
        for name, case in _ROUTINES.items():
            with self.subTest(routine=name):
                visited, _ = _red_walk(
                    case, {"run_log": _PROVIDER_LOG, "change_marker": _MARKER}
                )
                self.assertEqual(visited[-1], "precode")

    def test_a_hung_run_is_halted_before_the_signature(self) -> None:
        for name, case in _ROUTINES.items():
            with self.subTest(routine=name):
                visited, _ = _red_walk(
                    case,
                    {
                        "run_log": _ROLE_LOG,
                        "output_timestamps": [0.0],
                        "polled_at": SILENCE_SECONDS + 1,
                    },
                )
                self.assertEqual(visited[visited.index("hung") + 1], "halt")

    def test_a_silent_running_run_is_halted(self) -> None:
        for name, case in _ROUTINES.items():
            with self.subTest(routine=name):
                running = dict.fromkeys(case["red_runs"], RUNNING)
                visited, _ = _red_walk(
                    case,
                    {
                        **running,
                        "run_log": _ROLE_LOG,
                        "started_at": 0.0,
                        "polled_at": SILENCE_SECONDS + 1,
                    },
                )
                self.assertEqual(visited[visited.index("hung") + 1], "halt")

    def test_every_decision_lands_in_the_ledger(self) -> None:
        for name, case in _ROUTINES.items():
            with self.subTest(routine=name), tempfile.TemporaryDirectory() as tmp:
                ledger = Path(tmp) / "ledger.jsonl"
                visited, _ = _red_walk(
                    case, {"run_log": _ROLE_LOG, "ledger": str(ledger)}
                )
                decisions = {
                    step.id
                    for step in case["module"].STEPS
                    if step.kind == "decision" and step.fn is not None
                }
                lines = written_text(ledger).splitlines()
                self.assertEqual(
                    [json.loads(line)["step"] for line in lines],
                    [step_id for step_id in visited if step_id in decisions],
                )


if __name__ == "__main__":
    unittest.main()
