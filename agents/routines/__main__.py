"""Command line for agent routines.

- ``python -m agents.routines list`` prints every routine.
- ``python -m agents.routines show <routine>`` prints the ordered steps and
  the Mermaid diagram, needing no LangGraph.
- ``python -m agents.routines run <routine>`` builds and invokes the graph;
  each ``--scope <path>`` scopes the run to that changed file, under the
  state key ``scope``; each ``--override <policy>=<value>`` is an operator
  override of a routine policy, handed to the run under ``overrides``,
  recorded in the ``--ledger`` and printed in the result line. An ``ask`` step
  sends its question to the ``--owner`` and waits for the reply on stdin;
  without an owner it aborts the run. With ``--log <file>`` the run goes to a
  child process group whose output is copied to the log; a failed log write
  kills that group and aborts the run.
- ``python -m agents.routines decide <routine> <step> --state <json>`` runs one
  decision step over a JSON state file for an agent following the routine by
  hand, writes the state back and prints the chosen branch label; a missing
  state file needs ``--init``, and a state key of the wrong type is refused.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from agents.routines import discover, load
from agents.routines.contract import (
    EVIDENCE_SOURCE_KEY,
    LEDGER_KEY,
    AbortError,
    append_record,
    build,
)
from agents.routines.iterate import STATE_KEYS, check_state
from agents.routines.tools.log_scan import run_status
from agents.routines.tools.watchdog import CGROUP_MOUNT, process_ticks, stack_usage
from utils.orchestrator.channels import MatrixChannel

if TYPE_CHECKING:
    from collections.abc import Callable

    from agents.routines.contract import Step
    from utils.orchestrator.channels import Channel

SCOPE_KEY = "scope"
OVERRIDES_KEY = "overrides"
APPROVE = "approve"
ABORTED_EXIT = 3
LOG_FAILED_EXIT = 4


def _show(name: str) -> int:
    module = load(name)
    steps = getattr(module, "STEPS", [])
    mermaid = getattr(module, "MERMAID", "")
    print(f"# {name}\n")
    for index, step in enumerate(steps, start=1):
        label = getattr(step, "label", step)
        kind = getattr(step, "kind", "")
        suffix = f"  ({kind})" if kind and kind != "deterministic" else ""
        print(f"{index}. {label}{suffix}")
    if mermaid:
        print(f"\n```mermaid\n{mermaid}\n```")
    return 0


def _overrides(pairs: list[str]) -> dict[str, str]:
    overrides = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise ValueError(f"override {pair!r} is no <policy>=<value>")
        overrides[key] = value
    return overrides


def ask_owner(
    channel: Channel,
    owner: str,
    send: Callable[[dict], None],
    reply: Callable[[], str],
) -> Callable[[Step, dict], bool]:
    """Return the approval an ``ask`` step pauses on: it sends the step's
    question to ``owner`` through ``channel`` and waits for the reply; only
    ``approve`` approves, any other reply or none rejects.

    Args:
        channel: the channel the request goes through, as ``Channel``.
        owner: the owner's account.
        send: delivers the request ``channel.envelope`` returns.
        reply: blocks until the owner answers and returns the answer; ``""``
            when no answer came.
    """

    def approve(step: Step, state: dict) -> bool:
        send(channel.envelope(owner, f"{step.id}: {step.label}"))
        return reply().strip() == APPROVE

    return approve


def _unattended(step: Step, state: dict) -> bool:
    print(f"step {step.id!r} asks the owner; no --owner to ask", file=sys.stderr)
    return False


def _emit(request: dict) -> None:
    print(json.dumps({"approval_request": request}, ensure_ascii=False), flush=True)


def _run(
    name: str,
    scope: list[str],
    overrides: dict[str, str],
    ledger: str,
    approve: Callable[[Step, dict], bool],
) -> int:
    module = load(name)
    state: dict = {LEDGER_KEY: ledger} if ledger else {}
    if scope:
        state[SCOPE_KEY] = scope
    if overrides:
        state[OVERRIDES_KEY] = overrides
        append_record(ledger, OVERRIDES_KEY, overrides, "accepted")
    shown = " ".join(f"{key}={value}" for key, value in sorted(overrides.items()))
    suffix = f"; overrides: {shown}" if shown else ""
    try:
        build(name, module.STEPS, approve).invoke(state)
    except AbortError as error:
        print(f"{name}: aborted at {error.step}{suffix}")
        return ABORTED_EXIT
    print(f"{name}: done{suffix}")
    return 0


def _without_log(argv: list[str]) -> list[str]:
    kept: list[str] = []
    skip = False
    for arg in argv:
        if skip:
            skip = False
        elif arg == "--log":
            skip = True
        elif not arg.startswith("--log="):
            kept.append(arg)
    return kept


def supervise(argv: list[str], log: Path) -> int:
    """Run ``argv`` in its own process group and copy each output line to
    ``log`` and stdout; a failed log write kills the whole group, so the run
    stops and leaves no orphaned child process.

    Args:
        argv: the command line of the run.
        log: the run's log, appended to.

    Returns:
        The run's exit status, or ``LOG_FAILED_EXIT`` after a failed write.
    """
    with subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ) as child:
        try:
            with log.open("a", encoding="utf-8") as handle:
                for line in child.stdout:
                    handle.write(line)
                    handle.flush()
                    sys.stdout.write(line)
        except OSError as error:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(child.pid, signal.SIGKILL)
            print(
                f"log write to {log} failed ({error.strerror}); run aborted",
                file=sys.stderr,
            )
            return LOG_FAILED_EXIT
    return child.returncode


def _evidence(args: argparse.Namespace) -> dict:
    """Return the state keys the run's files and the poll carry: the log text
    and its last write time, the JUnit report, the exit status a run that
    ended wrote, the CPU each stack cgroup used, the poll time, and the
    evidence source naming them.

    A named exit status file that does not exist yet is reported on stderr and
    the run counts as still going; a ``--pid`` that is gone counts as ended.

    Args:
        args: the parsed ``decide`` arguments ``log``, ``junit``,
            ``exit_file``, ``pid``, ``cgroup`` and ``running``.
    """
    evidence: dict = {}
    if args.log:
        log = Path(args.log)
        evidence["run_log"] = log.read_text(encoding="utf-8", errors="replace")
        evidence["output_timestamps"] = [log.stat().st_mtime]
    if args.junit:
        evidence["junit_xml"] = Path(args.junit).read_text(encoding="utf-8")
    if args.exit_file:
        exit_file = Path(args.exit_file)
        if exit_file.is_file():
            evidence["exit_code"] = exit_file.read_text(encoding="utf-8").strip()
        else:
            print(f"no exit status file {args.exit_file!r} yet", file=sys.stderr)
    if args.pid is not None:
        ticks = process_ticks(args.pid)
        if ticks is None:
            evidence.setdefault(
                "exit_code", run_status(evidence.get("run_log", "")) or "gone"
            )
        else:
            evidence["process_ticks"] = ticks
    if args.cgroup:
        usage = stack_usage(args.cgroup, CGROUP_MOUNT)
        if usage is None:
            print(f"a stack cgroup of {args.cgroup} is gone", file=sys.stderr)
        else:
            evidence["stack_cpu_usec"] = usage
    if args.running:
        evidence["polled_at"] = time.time()
    sources = [
        f"{name}:{value}"
        for name, value in (
            ("log", args.log),
            ("junit", args.junit),
            ("exit", args.exit_file),
            ("pid", args.pid),
            *(("cgroup", cgroup) for cgroup in args.cgroup),
        )
        if value is not None
    ]
    if sources:
        evidence[EVIDENCE_SOURCE_KEY] = " ".join(sources)
    return evidence


def _read_state(args: argparse.Namespace) -> dict:
    path = Path(args.state)
    if not path.is_file():
        if not args.init:
            raise ValueError(
                f"no state file {args.state!r}; pass --init to start a new one"
            )
        return {}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"state file {args.state!r} is no JSON: {error}") from error
    check_state(state)
    return state


def _decide(args: argparse.Namespace) -> int:
    steps = {step.id: step for step in getattr(load(args.routine), "STEPS", [])}
    step = steps.get(args.step)
    if step is None or step.kind != "decision" or step.fn is None:
        print(
            f"no decision step '{args.step}' with a callable in '{args.routine}'",
            file=sys.stderr,
        )
        return 1
    wait = steps.get("wait")
    runs = (
        [target for _, target in wait.branches if steps[target].kind != "terminal"]
        if wait
        else []
    )
    if args.running and args.running not in runs:
        print(
            f"no run step '{args.running}' in '{args.routine}'; one of {', '.join(runs)}",
            file=sys.stderr,
        )
        return 1
    try:
        state = _read_state(args)
        if args.running:
            state["running_step"] = args.running
        evidence = _evidence(args)
        result = step.fn({**state, **evidence})
    except (ValueError, TypeError, SyntaxError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    path = Path(args.state)
    for key in evidence:
        result.pop(key, None)
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=sorted)
        + "\n",
        encoding="utf-8",
    )
    print(result[args.step])
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agents.routines")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    show = sub.add_parser("show")
    show.add_argument("routine")
    run = sub.add_parser("run", allow_abbrev=False)
    run.add_argument("routine")
    run.add_argument(
        "--scope", action="append", default=[], help="a changed file the run covers"
    )
    run.add_argument(
        "--override",
        action="append",
        default=[],
        help="an operator override of a routine policy, as <policy>=<value>",
    )
    run.add_argument("--ledger", default="", help="the run's ledger, an absolute path")
    run.add_argument("--owner", help="the account an ask step asks")
    run.add_argument("--homeserver", help="the Matrix homeserver of the owner")
    run.add_argument("--log", help="the run's log; a failed write aborts the run")
    decide = sub.add_parser(
        "decide",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="state keys:\n"
        + "\n".join(f"  {key}: {meaning}" for key, (*_, meaning) in STATE_KEYS.items()),
    )
    decide.add_argument("routine")
    decide.add_argument("step")
    decide.add_argument("--state", required=True, help="the JSON state file")
    decide.add_argument(
        "--init", action="store_true", help="start a new state file if none exists"
    )
    decide.add_argument("--log", help="the run's log")
    decide.add_argument("--junit", help="the run's JUnit report")
    decide.add_argument("--exit-file", help="the exit status file of a run that ended")
    decide.add_argument(
        "--pid", type=int, help="the run's process id, for the idle and exit check"
    )
    decide.add_argument(
        "--cgroup",
        action="append",
        default=[],
        help="the cgroup directory of one stack container, for the stack CPU check",
    )
    decide.add_argument(
        "--running", help="the id of the run step still going, for the watchdog poll"
    )
    raw = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(raw)

    if args.command == "list":
        for name in discover():
            print(name)
        return 0
    if args.command == "run" and args.owner and not args.homeserver:
        parser.error("--owner needs --homeserver")
    if args.command == "run" and args.log:
        return supervise(
            [sys.executable, "-m", "agents.routines", *_without_log(raw)],
            Path(args.log),
        )
    try:
        if args.command == "show":
            return _show(args.routine)
        if args.command == "decide":
            return _decide(args)
        approve = (
            ask_owner(
                MatrixChannel(args.homeserver), args.owner, _emit, sys.stdin.readline
            )
            if args.owner
            else _unattended
        )
        return _run(
            args.routine, args.scope, _overrides(args.override), args.ledger, approve
        )
    except KeyError:
        print(f"no routine '{args.routine}'", file=sys.stderr)
        return 1
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
