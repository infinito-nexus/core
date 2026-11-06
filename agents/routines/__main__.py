"""Command line for agent routines.

- ``python -m agents.routines list`` prints every routine.
- ``python -m agents.routines show <routine>`` prints the ordered steps and
  the Mermaid diagram, needing no LangGraph.
- ``python -m agents.routines run <routine>`` builds and invokes the graph.
- ``python -m agents.routines decide <routine> <step> --state <json>`` runs one
  decision step over a JSON state file for an agent following the routine by
  hand, writes the state back and prints the chosen branch label; a missing
  state file needs ``--init``, and a state key of the wrong type is refused.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from agents.routines import discover, load
from agents.routines.iterate import STATE_KEYS, check_state
from agents.routines.tools.log_scan import run_status
from agents.routines.tools.watchdog import process_ticks


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


def _run(name: str) -> int:
    module = load(name)
    graph = module.build()
    graph.invoke({})
    return 0


def _evidence(args: argparse.Namespace) -> dict:
    """Return the state keys the run's files and the poll carry: the log text
    and its last write time, the JUnit report, the exit status a run that
    ended wrote, and the poll time.

    A named exit status file that does not exist yet is reported on stderr and
    the run counts as still going; a ``--pid`` that is gone counts as ended.

    Args:
        args: the parsed ``decide`` arguments ``log``, ``junit``,
            ``exit_file``, ``pid`` and ``running``.
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
    if args.running:
        evidence["polled_at"] = time.time()
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
    run = sub.add_parser("run")
    run.add_argument("routine")
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
        "--running", help="the id of the run step still going, for the watchdog poll"
    )
    args = parser.parse_args(argv)

    if args.command == "list":
        for name in discover():
            print(name)
        return 0
    try:
        if args.command == "show":
            return _show(args.routine)
        if args.command == "decide":
            return _decide(args)
        return _run(args.routine)
    except KeyError:
        print(f"no routine '{args.routine}'", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
