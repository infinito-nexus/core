"""Load, validate, select and report the agent verification scenarios.

Each acceptance criterion that only a running stack can prove carries a
scenario under ``agents/scenarios/`` (see that directory's ``README.md``): a
flat YAML document with ``id``, ``criterion``, ``mode``, ``given``, ``when``
and ``then``. ``make agents-verify`` deploys the agents bundle and calls this
module to run the selected scenarios and print the one result table the
requirement asks for: id, mode, result, duration, log path.

Loading, validation, selection and table formatting are stack-free and unit
tested here. Playing a scenario against the running stack is deploy-coupled and
owned by CI; it is isolated in :func:`run_scenario`, the single seam, so
nothing else in this module touches a stack. The flat documents are parsed with
the standard library so the module keeps no YAML dependency.

Usage: ``python -m cli.agents.scenarios [--scenario <id>] [--mode compose|swarm] [--list]``.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text

SCENARIOS_DIR = PROJECT_ROOT / "agents" / "scenarios"
REQUIRED_FIELDS = ("id", "criterion", "mode", "given", "when", "then")
VALID_MODES = ("compose", "swarm")
LOG_DIR = Path(tempfile.gettempdir()) / "agents-scenarios"


class ScenarioError(ValueError):
    """A scenario document lacks a required field or declares an unknown mode."""


@dataclass(frozen=True)
class Scenario:
    id: str
    criterion: str
    mode: str
    given: str
    when: str
    then: str
    source: str


@dataclass(frozen=True)
class ScenarioResult:
    id: str
    mode: str
    result: str
    duration: float
    log_path: str


def parse_scenario(text: str, source: str) -> Scenario:
    """Parse one flat scenario document and validate it.

    The documents are a flat ``key: value`` mapping (see
    ``agents/scenarios/README.md``). Raises :class:`ScenarioError` when a
    required field is missing or empty, or when ``mode`` is not one of
    :data:`VALID_MODES`.

    Args:
        text: the scenario document.
        source: a human-readable origin (path or ``<inline>``) for error text.
    """
    fields: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line in ("---", "...") or line.startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise ScenarioError(f"{source}: line without a key: {raw!r}")
        cleaned = value.strip()
        if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in "'\"":
            cleaned = cleaned[1:-1]
        fields[key.strip()] = cleaned
    missing = [name for name in REQUIRED_FIELDS if not fields.get(name)]
    if missing:
        raise ScenarioError(f"{source}: missing field(s): {', '.join(missing)}")
    if fields["mode"] not in VALID_MODES:
        raise ScenarioError(
            f"{source}: mode {fields['mode']!r} is not one of {VALID_MODES}"
        )
    return Scenario(
        id=fields["id"],
        criterion=fields["criterion"],
        mode=fields["mode"],
        given=fields["given"],
        when=fields["when"],
        then=fields["then"],
        source=source,
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
    """Return the scenarios chosen by id (one) and/or by mode.

    Raises :class:`ScenarioError` when *scenario_id* matches nothing.
    """
    chosen = list(scenarios)
    if scenario_id is not None:
        chosen = [scenario for scenario in chosen if scenario.id == scenario_id]
        if not chosen:
            raise ScenarioError(f"no scenario with id {scenario_id!r}")
    if mode is not None:
        chosen = [scenario for scenario in chosen if scenario.mode == mode]
    return chosen


def _log_path(scenario_id: str) -> Path:
    return LOG_DIR / f"{scenario_id}.log"


def _default_execute(scenario: Scenario, log_path: Path) -> str:
    """Record that playback was not performed here and report ``skipped``.

    Playing a scenario is deploy-coupled: the deployed harness drives it against
    the running stack under CI. With no stack to drive, the honest result is
    ``skipped`` (never a fabricated pass); CI supplies an executor that shells
    out to the documented ``make compose-exec`` interface instead.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as handle:
        handle.write(
            f"skipped {scenario.id} ({scenario.mode}): scenario playback is "
            "deploy-coupled and runs under CI with the agents bundle deployed.\n"
        )
    return "skipped"


def run_scenario(scenario: Scenario, *, execute=_default_execute) -> ScenarioResult:
    """Run one scenario against the already-running stack and return its row.

    This is the single deploy-coupled seam the main path calls per scenario.
    *execute* performs the stack interaction and returns the result word
    (``passed`` / ``failed`` / ``skipped``); it is injected so the surrounding
    selection and reporting logic is tested without a stack. The default
    executor does not touch a stack (see :func:`_default_execute`).
    """
    log_path = _log_path(scenario.id)
    start = time.monotonic()
    result = execute(scenario, log_path)
    duration = round(time.monotonic() - start, 3)
    return ScenarioResult(scenario.id, scenario.mode, result, duration, str(log_path))


def run_all(
    scenarios: list[Scenario], *, execute=_default_execute
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cli.agents.scenarios")
    parser.add_argument("--scenario")
    parser.add_argument("--mode", choices=VALID_MODES)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)

    scenarios = select(load_scenarios(), scenario_id=args.scenario, mode=args.mode)
    if args.list:
        for scenario in scenarios:
            print(scenario.id)
        return 0

    results = run_all(scenarios)
    print(format_table(results))
    return 1 if any(r.result == "failed" for r in results) else 0


def _expect(condition: bool, message: object) -> None:
    if not condition:
        raise AssertionError(message)


def _demo() -> None:
    sample = (
        "---\n"
        "id: demo-probe\n"
        "criterion: SC-DEMO\n"
        "mode: compose\n"
        "given: a seeded fixture\n"
        "when: the probe runs\n"
        "then: the observable holds\n"
    )
    other = sample.replace("demo-probe", "demo-swarm").replace("compose", "swarm")

    scenario = parse_scenario(sample, "<inline>")
    _expect(scenario.id == "demo-probe", scenario)
    _expect(scenario.mode == "compose", scenario)
    _expect(scenario.then == "the observable holds", scenario)

    scenarios = [scenario, parse_scenario(other, "<inline>")]
    _expect(
        [s.id for s in select(scenarios, mode="swarm")] == ["demo-swarm"], scenarios
    )
    _expect(
        [s.id for s in select(scenarios, scenario_id="demo-probe")] == ["demo-probe"],
        scenarios,
    )

    for broken in (
        "id: x\ncriterion: y\nmode: k8s\ngiven: g\nwhen: w\nthen: t\n",
        "id: x\nmode: compose\n",
    ):
        try:
            parse_scenario(broken, "<inline>")
        except ScenarioError:
            continue
        raise AssertionError(f"expected ScenarioError for {broken!r}")

    passed = run_scenario(scenario, execute=lambda _scenario, _log: "passed")
    _expect(passed.result == "passed" and passed.duration >= 0.0, passed)
    results = [
        passed,
        run_scenario(scenarios[1], execute=lambda _scenario, _log: "failed"),
    ]
    table = format_table(results)
    _expect("demo-probe" in table and "duration" in table, table)
    _expect(any(r.result == "failed" for r in results), results)
    print("agents scenarios self-check ok")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        _demo()
    else:
        raise SystemExit(main())
