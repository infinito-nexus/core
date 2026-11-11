"""Load, validate, select, play and report the agent verification scenarios.

Each acceptance criterion that only a running stack can prove carries a
scenario under ``agents/scenarios/`` (see that directory's ``README.md``): a
YAML document with ``id``, ``criterion``, ``mode``, ``given``, ``when`` and
``then``, plus the ``steps`` that play it and the inventory credentials it
``requires``. ``call-test-agents-local.yml`` deploys the agents bundle and calls
this module to play the scenarios and print the one result table the
requirement asks for: id, mode, result, duration, log path.

A scenario passes only when every step ran against the stack and exited and
printed what the step declares. It reports ``skipped``, never ``passed``, when
it declares no steps or when a credential it requires is not set. The runner
(:func:`stack_runner`) is the one seam that touches the stack; tests replay
recorded step outputs through it, so playback is proven without a stack.

Usage: ``python -m cli.agents.scenarios [--scenario <id>] [--mode compose|swarm] [--list]``.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from cli.administration.deploy.development.common import DEV_INVENTORY_VARS_FILE
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml, load_yaml_str

SCENARIOS_DIR = PROJECT_ROOT / "agents" / "scenarios"
EXEC_SCRIPT = PROJECT_ROOT / "scripts" / "tests" / "deploy" / "local" / "exec"
REQUIRED_FIELDS = ("id", "criterion", "mode", "given", "when", "then")
STEP_FIELDS = ("run", "expect", "exit")
DEPLOY_MODES = ("compose", "swarm")
VALID_MODES = (*DEPLOY_MODES, "both")
STEP_TIMEOUT_SECONDS = 900
TIMEOUT_EXIT = 124
LOG_DIR = Path(tempfile.gettempdir()) / "agents-scenarios"
_ENV_LOOKUP = re.compile(
    r"^\{\{\s*lookup\(\s*['\"]env['\"]\s*,\s*['\"](\w+)['\"]\s*\)\s*\}\}$"
)

Runner = Callable[[str], tuple[int, str]]


class ScenarioError(ValueError):
    """A scenario lacks a required field, declares an unknown mode or a broken step."""


@dataclass(frozen=True)
class Step:
    run: str
    expect: str
    exit: int


@dataclass(frozen=True)
class Scenario:
    id: str
    criterion: str
    mode: str
    given: str
    when: str
    then: str
    source: str
    requires: tuple[str, ...] = ()
    steps: tuple[Step, ...] = ()


@dataclass(frozen=True)
class ScenarioResult:
    id: str
    mode: str
    result: str
    duration: float
    log_path: str


def _parse_step(raw: object, source: str, index: int) -> Step:
    where = f"{source}: step {index}"
    if not isinstance(raw, dict) or not str(raw.get("run") or "").strip():
        raise ScenarioError(f"{where} has no run command")
    unknown = sorted(set(raw) - set(STEP_FIELDS))
    if unknown:
        raise ScenarioError(f"{where} has unknown field(s): {', '.join(unknown)}")
    expect = raw.get("expect", "")
    code = raw.get("exit", 0)
    if not isinstance(expect, str) or type(code) is not int:
        raise ScenarioError(f"{where}: expect must be a pattern, exit an integer")
    try:
        re.compile(expect)
    except re.error as error:
        raise ScenarioError(f"{where}: expect is no valid pattern: {error}") from error
    return Step(run=str(raw["run"]), expect=expect, exit=code)


def parse_scenario(text: str, source: str) -> Scenario:
    """Parse one scenario document and validate it.

    Raises :class:`ScenarioError` when a required field is missing or empty,
    ``mode`` is not one of :data:`VALID_MODES`, ``requires`` is not a list of
    inventory paths, or a step lacks its ``run`` command or carries a broken
    ``expect`` pattern or ``exit`` code.

    Args:
        text: the scenario document.
        source: a human-readable origin (path or ``<inline>``) for error text.
    """
    data = load_yaml_str(text)
    if not isinstance(data, dict):
        raise ScenarioError(f"{source}: not a mapping")
    fields = {name: str(data.get(name) or "").strip() for name in REQUIRED_FIELDS}
    missing = [name for name, value in fields.items() if not value]
    if missing:
        raise ScenarioError(f"{source}: missing field(s): {', '.join(missing)}")
    if fields["mode"] not in VALID_MODES:
        raise ScenarioError(
            f"{source}: mode {fields['mode']!r} is not one of {VALID_MODES}"
        )
    requires = data.get("requires") or []
    if not isinstance(requires, list) or not all(
        isinstance(path, str) and path for path in requires
    ):
        raise ScenarioError(f"{source}: requires must list inventory paths")
    steps = data.get("steps") or []
    if not isinstance(steps, list):
        raise ScenarioError(f"{source}: steps must be a list")
    return Scenario(
        **fields,
        source=source,
        requires=tuple(requires),
        steps=tuple(
            _parse_step(raw, source, index) for index, raw in enumerate(steps, 1)
        ),
    )


def load_scenarios(directory: Path = SCENARIOS_DIR) -> list[Scenario]:
    """Return every ``*.yml`` scenario under *directory*, validated, sorted by id."""
    scenarios = [
        parse_scenario(read_text(str(path)), str(path))
        for path in sorted(directory.glob("*.yml"))
    ]
    return sorted(scenarios, key=lambda scenario: scenario.id)


def select(
    scenarios: list[Scenario],
    *,
    scenario_id: str | None = None,
    mode: str | None = None,
) -> list[Scenario]:
    """Return the scenarios chosen by id (one) and/or by deploy mode.

    A scenario of mode ``both`` belongs to either deploy mode. Raises
    :class:`ScenarioError` when *scenario_id* matches nothing.
    """
    chosen = list(scenarios)
    if scenario_id is not None:
        chosen = [scenario for scenario in chosen if scenario.id == scenario_id]
        if not chosen:
            raise ScenarioError(f"no scenario with id {scenario_id!r}")
    if mode is not None:
        chosen = [scenario for scenario in chosen if scenario.mode in (mode, "both")]
    return chosen


def _is_set(inventory: dict, path: str) -> bool:
    value: object = inventory
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            return False
        value = value[key]
    match = _ENV_LOOKUP.match(value.strip()) if isinstance(value, str) else None
    if match:
        value = os.environ.get(match.group(1))
    return bool(value)


def missing_credentials(scenario: Scenario, inventory: dict) -> list[str]:
    """Return the ``requires`` paths the inventory leaves unset.

    A value of the form ``{{ lookup('env', 'NAME') }}`` is read from the
    environment, where the deploy reads it as well.

    Args:
        scenario: the scenario whose ``requires`` is checked.
        inventory: the inventory variables of the deploy.
    """
    return [path for path in scenario.requires if not _is_set(inventory, path)]


def stack_runner(command: str) -> tuple[int, str]:
    """Run *command* in the running stack container; return exit code and output.

    Args:
        command: the shell command of one scenario step.
    """
    # Exception: make compose-exec quotes cmd='$(cmd)', which a quote in a step breaks, so its script gets argv.
    try:
        done = subprocess.run(
            ["bash", str(EXEC_SCRIPT / "container.sh"), "sh", "-lc", command],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=STEP_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return TIMEOUT_EXIT, f"timed out after {STEP_TIMEOUT_SECONDS}s\n"
    return done.returncode, done.stdout + done.stderr


def play(scenario: Scenario, log_path: Path, *, runner: Runner, inventory: dict) -> str:
    """Play *scenario* step by step through *runner* and return its result word.

    Every step command, its exit code and its output land in *log_path*. The
    first step that exits otherwise than declared, or whose output lacks its
    ``expect`` pattern, fails the scenario and ends it.

    Args:
        scenario: the scenario to play.
        log_path: the scenario's log file.
        runner: runs one step command against the stack, returns exit and output.
        inventory: the inventory variables ``requires`` is checked against.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        missing = missing_credentials(scenario, inventory)
        if missing:
            log.write(f"skipped {scenario.id}: credential(s) not set: {missing}\n")
            return "skipped"
        if not scenario.steps:
            log.write(f"skipped {scenario.id}: the scenario declares no steps\n")
            return "skipped"
        for index, step in enumerate(scenario.steps, 1):
            code, output = runner(step.run)
            log.write(f"$ {step.run}\n{output}\n[step {index} exit {code}]\n")
            if code != step.exit:
                log.write(f"failed: step {index} exited {code}, not {step.exit}\n")
                return "failed"
            if not re.search(step.expect, output):
                log.write(f"failed: step {index} printed no {step.expect!r}\n")
                return "failed"
        log.write(f"passed {scenario.id}: {len(scenario.steps)} step(s)\n")
    return "passed"


def _log_path(scenario_id: str) -> Path:
    return LOG_DIR / f"{scenario_id}.log"


def run_scenario(
    scenario: Scenario, *, execute: Callable[[Scenario, Path], str]
) -> ScenarioResult:
    """Run one scenario through *execute* and return its result row.

    Args:
        scenario: the scenario to run.
        execute: plays the scenario into its log and returns ``passed``,
            ``failed`` or ``skipped`` (:func:`play` bound to a runner).
    """
    log_path = _log_path(scenario.id)
    start = time.monotonic()
    result = execute(scenario, log_path)
    duration = round(time.monotonic() - start, 3)
    return ScenarioResult(scenario.id, scenario.mode, result, duration, str(log_path))


def run_all(
    scenarios: list[Scenario], *, execute: Callable[[Scenario, Path], str]
) -> list[ScenarioResult]:
    """Run every scenario in order and return the per-scenario results."""
    return [run_scenario(scenario, execute=execute) for scenario in scenarios]


def format_table(results: list[ScenarioResult]) -> str:
    """Render the result rows as the one result table the agent scenarios print.

    Columns: id, mode, result, duration, log path.
    """
    header = ("id", "mode", "result", "duration", "log")
    rows = [(r.id, r.mode, r.result, f"{r.duration:.1f}s", r.log_path) for r in results]
    widths = [
        max([len(header[i])] + [len(row[i]) for row in rows])
        for i in range(len(header))
    ]

    def _row(columns: tuple[str, ...]) -> str:
        return "  ".join(col.ljust(widths[i]) for i, col in enumerate(columns))

    lines = [_row(header), _row(tuple("-" * width for width in widths))]
    lines.extend(_row(row) for row in rows)
    return "\n".join(lines)


def main(argv: list[str] | None = None, *, runner: Runner = stack_runner) -> int:
    """Play the selected scenarios and print the result table.

    Args:
        argv: the command line, ``sys.argv[1:]`` when None.
        runner: runs one step command against the stack.
    """
    parser = argparse.ArgumentParser(prog="cli.agents.scenarios")
    parser.add_argument("--scenario")
    parser.add_argument("--mode", choices=DEPLOY_MODES)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)

    scenarios = select(load_scenarios(), scenario_id=args.scenario, mode=args.mode)
    if args.list:
        for scenario in scenarios:
            print(scenario.id)
        return 0

    inventory = load_yaml(str(PROJECT_ROOT / DEV_INVENTORY_VARS_FILE))
    results = run_all(
        scenarios, execute=partial(play, runner=runner, inventory=inventory)
    )
    print(format_table(results))
    return 1 if any(r.result == "failed" for r in results) else 0


def _expect(condition: bool, message: object) -> None:
    if not condition:
        raise AssertionError(message)


def _demo() -> None:
    sample = (
        "id: demo-probe\n"
        "criterion: SC-DEMO\n"
        "mode: compose\n"
        "given: a seeded fixture\n"
        "when: the probe runs\n"
        "then: the observable holds\n"
        "steps:\n"
        "  - run: probe\n"
        "    expect: ^ok\n"
    )
    scenario = parse_scenario(sample, "<inline>")
    _expect(scenario.steps == (Step("probe", "^ok", 0),), scenario)
    other = parse_scenario(sample.replace("compose", "swarm"), "<inline>")
    _expect(select([scenario, other], mode="swarm") == [other], other)

    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "demo.log"

        def replay(output: str) -> str:
            return play(scenario, log, runner=lambda _cmd: (0, output), inventory={})

        _expect(replay("ok\n") == "passed", "a matching step passes")
        _expect(replay("no\n") == "failed", "a step without its match fails")
    print("agents scenarios self-check ok")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        _demo()
    else:
        raise SystemExit(main())
