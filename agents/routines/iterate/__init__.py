"""Shared decision steps of the iterate routines: the relevant-delta check before
a rerun, and the red chain a red or still-running run passes before the loop
inspects it (the watchdog, the reached check and the signature stop rule).
Every decision writes its branch label under its step id and appends one record
to the ledger (``agents.routines.contract.decide``). A decision without its
evidence takes its first branch, so a stub run reaches a terminal. An agent
following a routine by hand runs a decision with ``python -m agents.routines
decide <routine> <step> --state <state.json>``, which every label names; the
state keys it reads are ``STATE_KEYS``.
"""

from __future__ import annotations

from functools import partial

from agents.routines.contract import Step, decide
from agents.routines.tools.delta import relevant, role_ids
from agents.routines.tools.junit import failures
from agents.routines.tools.log_scan import change_ran, mentions, reached, run_status
from agents.routines.tools.signature import (
    failure_signature,
    hung_signature,
    repeated,
)
from agents.routines.tools.watchdog import (
    BUSY_CORES,
    SILENCE_SECONDS,
    is_hung,
    stack_busy,
)

CHANGED = "✏️ changed"
UNCHANGED = "⏸️ unchanged"
RUNNING = "⏳ running"
ENDED = "▶️ ended"
GREEN = "✅ ended green"
GREEN_RUN = "✅ green"
HUNG = "🧊 hung"
ALIVE = "📝 still writing"
REACHED = "🎯 reached"
PRE_CODE = "⏮️ pre-code"
NEW = "🆕 new"
REPEATED = "🔁 repeated"
NO_RUN_STEP = "❔ poll again with --running <run step>"
DECIDE = "python -m agents.routines decide"
TUNE_VELOCITY = "tune_velocity"
TUNE_DESIGN = "tune_design"
_NUMBER = (int, float)
_LIST = (list, tuple, set, frozenset)

STATE_KEYS = {
    "ledger": (
        str,
        None,
        "the JSON Lines ledger, an absolute path; '' records nothing",
    ),
    "role": (str, None, "the role id under test"),
    "roles": (_LIST, str, "the role ids under test; none counts as changed"),
    "changed_paths": (
        _LIST,
        str,
        "git diff --name-only --no-renames <last_run_tree> <current tree>; absent counts as changed",
    ),
    "last_run_tree": (str, None, "the tree snapshot the last run started from"),
    "delta_affected": (
        str,
        None,
        "the affected-roles resolver line; '' counts as every role",
    ),
    "started_at": (_NUMBER, None, "epoch seconds of the run's start"),
    "output_timestamps": (_LIST, _NUMBER, "epoch seconds of the run's output"),
    "polled_at": (_NUMBER, None, "epoch seconds of a poll of a run still going"),
    "running_step": (str, None, "the id of the run step being polled"),
    "exit_code": (str, None, "the exit status a run that ended wrote; '0' is green"),
    "process_ticks": (int, None, "CPU ticks of the run's process tree at this poll"),
    "last_process_ticks": (
        int,
        None,
        "CPU ticks of the run's process tree at the poll before",
    ),
    "stack_cpu_usec": (
        _LIST,
        int,
        "CPU microseconds of each stack cgroup at this poll, in --cgroup order",
    ),
    "last_stack_cpu_usec": (
        _LIST,
        int,
        "CPU microseconds of each stack cgroup at the poll before",
    ),
    "last_polled_at": (_NUMBER, None, "epoch seconds of the poll before"),
    "evidence_source": (
        str,
        None,
        "where this iteration's evidence came from; the decide command sets it from its files",
    ),
    "run_log": (str, None, "the run's log"),
    "junit_xml": (str, None, "the run's JUnit report"),
    "change_marker": (
        str,
        None,
        "the text the changed code's first output line carries; '' counts as reached",
    ),
    "signatures": (_LIST, str, "the signatures of the red runs so far, oldest first"),
}


def check_state(state: object) -> None:
    """Refuse a state a decision would misread, naming the key.

    ``run_args`` and ``last_run_args`` take any JSON value and branch labels
    any string; a key set to ``null`` counts as absent; a list key also takes
    a tuple or set from a caller inside the graph.

    Args:
        state: the decoded state file or the state a graph node receives.

    Raises:
        TypeError: ``state`` is no JSON object, or a key of ``STATE_KEYS``
            holds a value of the wrong type.
    """
    if not isinstance(state, dict):
        raise TypeError("the state must be a JSON object")
    for key, (kind, item, meaning) in STATE_KEYS.items():
        value = state.get(key)
        if value is None:
            continue
        if not isinstance(value, kind) or (
            item is not None and not all(isinstance(entry, item) for entry in value)
        ):
            shape = {_LIST: "a list", _NUMBER: "a number"}.get(kind, "a string")
            raise TypeError(f"state key {key!r} must be {shape}: {meaning}")


def decide_command(routine: str, step: str, options: str) -> str:
    """Return the ``decide`` command line a label names for a step.

    Args:
        routine: the routine's flat name.
        step: the decision step id.
        options: the evidence options after ``--state``, ``""`` for none.
    """
    return f"{DECIDE} {routine} {step} --state <state.json>{options}"


def _relevant_delta(state: dict, runs_tests: bool) -> dict:
    check_state(state)
    roles = role_ids([*(state.get("roles") or []), state.get("role") or ""])
    paths = state.get("changed_paths")
    affected = state.get("delta_affected") or ""
    args_changed = state.get("run_args") != state.get("last_run_args")
    changed = (
        paths is None
        or args_changed
        or relevant(roles, list(paths), affected, runs_tests)
    )
    inputs = {
        "roles": roles,
        "changed_paths": paths,
        "last_run_tree": state.get("last_run_tree") or "",
        "delta_affected": affected,
        "args_changed": args_changed,
        "runs_tests": runs_tests,
    }
    return decide(state, "relevant_delta", inputs, CHANGED if changed else UNCHANGED)


def _hung(state: dict) -> dict:
    check_state(state)
    started_at = state.get("started_at")
    marks = [
        *(state.get("output_timestamps") or []),
        *([started_at] if started_at is not None else []),
    ]
    polled_at = state.get("polled_at")
    last_polled_at = state.get("last_polled_at")
    status = state.get("exit_code") or run_status(state.get("run_log") or "")
    ticks = state.get("process_ticks")
    tree_busy = ticks is not None and ticks != state.get("last_process_ticks")
    if ticks is not None:
        state["last_process_ticks"] = ticks
    usage = state.get("stack_cpu_usec")
    stack_working = stack_busy(
        usage,
        state.get("last_stack_cpu_usec"),
        None
        if polled_at is None or last_polled_at is None
        else polled_at - last_polled_at,
    )
    if usage is not None:
        state["last_stack_cpu_usec"] = usage
    if polled_at is not None:
        state["last_polled_at"] = polled_at
    busy = tree_busy or stack_working
    if status == "0":
        outcome = GREEN
        state["signatures"] = []
        running = state.get("running_step")
        if running:
            state[running] = GREEN_RUN
    elif polled_at is None or status is not None:
        outcome = ENDED
    elif not busy and is_hung(marks, polled_at, SILENCE_SECONDS):
        outcome = HUNG
    else:
        outcome = ALIVE
    inputs = {
        "last_output_at": max(marks) if marks else None,
        "polled_at": polled_at,
        "exit_status": status,
        "tree_busy": tree_busy,
        "stack_busy": stack_working,
        "silence": SILENCE_SECONDS,
    }
    return decide(state, "hung", inputs, outcome)


def _wait(state: dict, runs: tuple[str, ...]) -> dict:
    check_state(state)
    running = state.get("running_step") or ""
    outcome = running if running in runs else NO_RUN_STEP
    return decide(state, "wait", {"running_step": running}, outcome)


def _reached(state: dict) -> dict:
    check_state(state)
    marker = state.get("change_marker") or ""
    log = state.get("run_log") or ""
    junit_xml = state.get("junit_xml") or ""
    halted = state.get("hung") == HUNG
    failed = [case["name"] or "" for case in failures(junit_xml)] if junit_xml else []
    hit = (
        not marker
        or not (log or junit_xml)
        or bool(change_ran(log, marker))
        or any(marker in name for name in failed)
        or (mentions(log, marker) if halted else reached(log, marker))
    )
    inputs = {"change_marker": marker, "failed_cases": failed, "halted": halted}
    return decide(state, "reached", inputs, REACHED if hit else PRE_CODE)


def _signature(state: dict) -> dict:
    check_state(state)
    if state.get("hung") == GREEN:
        state["signatures"] = []
        return decide(state, "signature", {"red_runs": 0, "green": True}, NEW)
    log = state.get("run_log") or ""
    junit_xml = state.get("junit_xml") or ""
    halted = state.get("hung") == HUNG and not junit_xml
    current = hung_signature(log) if halted else failure_signature(log, junit_xml)
    previous = list(state.get("signatures") or [])
    again = repeated(previous, current)
    state["signatures"] = [*previous, current]
    inputs = {
        "red_runs": len(previous) + 1,
        "signed_text": bool(current),
        "halted": halted,
    }
    return decide(state, "signature", inputs, REPEATED if again else NEW)


def relevant_delta_step(
    routine: str, changed: str, unchanged: str, runs_tests: bool
) -> Step:
    """Return the decision that skips a rerun the last run already answered.

    Args:
        routine: the routine's flat name, for the decide command in the label.
        changed: the id of the rerun step a relevant change continues at.
        unchanged: the id of the step an unchanged delta returns to instead of
            a rerun that would repeat the last result.
        runs_tests: the rerun runs the test suite (``make test``, a
            workflow), so every changed path counts.
    """
    reads = (
        "every path counts, since the rerun runs the test suite"
        if runs_tests
        else "tests/ and docs left out; a path outside roles/ counts; another role counts when python -m cli.meta.roles.applications.resolution.affected --changed-roles <roles> lists one under test, its exit 2 as __ALL__"
    )
    return Step(
        "relevant_delta",
        f"Did a path the rerun reads, or the run's arguments, change since the last run? (snapshot the working tree when a run starts, one command each, <tmp index> a path that does not exist yet, since git refuses an empty pre-created file: GIT_INDEX_FILE=<tmp index> git add -A, then GIT_INDEX_FILE=<tmp index> git write-tree, its sha recorded as last_run_tree; changed_paths: a fresh snapshot, then git diff --name-only --no-renames <last_run_tree> <fresh tree>; {reads}); unchanged: no rerun; {decide_command(routine, 'relevant_delta', '')}",
        "decision",
        branches=((CHANGED, changed), (UNCHANGED, unchanged)),
        fn=partial(_relevant_delta, runs_tests=runs_tests),
    )


def companion_steps(done: str, design: bool) -> list[Step]:
    """Return the tuning companions a green run passes on its way to ``done``.

    Args:
        done: the id of the step the companions hand over to.
        design: whether the design companion follows the velocity companion.
    """
    velocity = Step(
        TUNE_VELOCITY,
        "Companion: python -m cli.tune.logscan <green run log> ranks the slowest tasks, per-item loops and retries; keep the scan beside the log as the collect and scan input of the perf_sweep routine (python -m agents.routines show perf_sweep), and never tune inside this loop",
        nxt=TUNE_DESIGN if design else done,
    )
    if not design:
        return [velocity]
    return [
        velocity,
        Step(
            TUNE_DESIGN,
            "Companion: follow the tune_design routine (python -m agents.routines show tune_design) with apps= the apps the compose stack still serves, disabled= the run's disable= and mode=compose; it screenshots them and files design proposals, and never edits a role",
            nxt=done,
        ),
    ]


def red_chain(routine: str, verdict: str, runs: tuple[str, ...]) -> list[Step]:
    """Return the steps a red or still-running run passes before the loop acts
    on it: the watchdog with its wait, the reached check, the signature stop
    rule and their three stops.

    Args:
        routine: the routine's flat name, for the decide command in the labels.
        verdict: the id of the step a red that reached the changed code with a
            new signature continues at.
        runs: the ids of the run steps that enter the chain; a run still
            writing output goes back to the one named in ``running_step``.
    """
    evidence = " --log <run log> [--junit <report>]"
    return [
        Step(
            "hung",
            f"Watchdog: is the run unfinished, silent for more than {SILENCE_SECONDS:.0f} s, counted from its start when it wrote none, with its process tree idle and no stack cgroup using {BUSY_CORES:g} core or more since the poll before? (agents/routines/tools/watchdog.py; while it runs: {decide_command(routine, 'hung', ' --log <run log> --running <run step> [--pid <run pid>] [--cgroup <stack cgroup>]...')}, one --cgroup per stack container, its cgroup directory such as /sys/fs/cgroup/system.slice/docker-<full container id>.scope; once it ended: {decide_command(routine, 'hung', ' --log <run log> [--exit-file <exit status file>]')}; the run ended on an exit status file, a gone --pid, the deploy wrapper's exit line, a make Error line, the deploy's Script ended line or a PLAY RECAP with a failed host, not on a PLAY RECAP alone, which may close one play of several; exit status 0 is green and returns to the run step)",
            "decision",
            branches=(
                (ENDED, "reached"),
                (HUNG, "halt"),
                (ALIVE, "wait"),
                (GREEN, "wait"),
            ),
            fn=_hung,
        ),
        Step(
            "wait",
            f"Keep waiting on the run still writing output (running_step), then take its verdict, the green one a green end wrote; without a known running_step, poll again ({decide_command(routine, 'wait', '')})",
            "decision",
            branches=(*((run, run) for run in runs), (NO_RUN_STEP, "poll")),
            fn=partial(_wait, runs=runs),
        ),
        Step(
            "poll",
            f"Stop: the poll named no run step; poll again with {decide_command(routine, 'hung', ' --log <run log> --running <run step>')}",
            "terminal",
        ),
        Step(
            "halt",
            "Stop the hung run and keep its log; the reached check reads the whole log, the signature the task it hangs in (its last TASK banner), else its last line",
            nxt="reached",
        ),
        Step(
            "reached",
            f"Did the run reach the changed code before its last failure? (the change marker on a line before the last fatal or [ERROR] cause line of the task the run ended in, rescued and ignored tasks and Ansible retries left out, the whole log for a halted run; a passed spec; or a failing JUnit case; {decide_command(routine, 'reached', evidence)})",
            "decision",
            branches=((REACHED, "signature"), (PRE_CODE, "precode")),
            fn=_reached,
        ),
        Step(
            "signature",
            f"Same failure signature as the red run before? (agents/routines/tools/signature.py: a digest of the failing JUnit cases, else of the failed Ansible task's banner, cause and fatal lines with the failed Playwright cases, volatile parts masked; two reds without failure text repeat; {decide_command(routine, 'signature', evidence)})",
            "decision",
            branches=((NEW, verdict), (REPEATED, "escalate")),
            fn=_signature,
        ),
        Step(
            "precode",
            "Stop: the red precedes the changed code, so it is no verdict on the change; debug it as its own cause, then restart this loop",
            "terminal",
        ),
        Step(
            "escalate",
            "Stop and escalate: the same failure signature twice in a row; hand the ledger and the last log to the operator instead of a third identical run",
            "terminal",
        ),
    ]
