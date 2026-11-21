"""The tools services inside the infra runner: their idle stop units and compose calls."""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.infra import SERVICE

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

TIMER = "infinito-tools-idle"
TIMER_PERIOD = "5min"
UNIT_DIR = ("infra", "systemd")
TOOLS_ACTIONS = ("stop", "pause", "unpause")


def idle_units(
    checkout: Path, python: str, environment: Mapping[str, str]
) -> dict[str, str]:
    """Args:
        checkout: read-only checkout root inside the runner, at its host path.
        python: interpreter of the runner image.
        environment: the idle grace and the stamp directory, by key.

    Returns:
        The systemd service and timer of the idle stop, by file name.
    """
    stop = f"{python} -m cli.administration.infra tools-inside stop"
    service = [
        "[Unit]",
        "Description=Stop the tools services of the infra runner once idle",
        "",
        "[Service]",
        "Type=oneshot",
        f"WorkingDirectory={checkout}",
        "Environment=PYTHONDONTWRITEBYTECODE=1",
        *(f"Environment={key}={value}" for key, value in sorted(environment.items())),
        f"ExecStart={python} -m utils.inventory.tools_idle stop-if-idle -- {stop}",
    ]
    timer = [
        "[Unit]",
        f"Description=Run {TIMER}.service every {TIMER_PERIOD}",
        "",
        "[Timer]",
        f"OnBootSec={TIMER_PERIOD}",
        f"OnUnitActiveSec={TIMER_PERIOD}",
        "",
        "[Install]",
        "WantedBy=timers.target",
    ]
    return {
        f"{TIMER}.service": "\n".join(service) + "\n",
        f"{TIMER}.timer": "\n".join(timer) + "\n",
    }


def write_units(unit_dir: Path, units: Mapping[str, str]) -> None:
    """Args:
    unit_dir: directory below the cache base, bound into the runner at its host path.
    units: file name to unit text.
    """
    unit_dir.mkdir(parents=True, exist_ok=True)
    for name, text in units.items():
        (unit_dir / name).write_text(text, encoding="utf-8")


def timer_installs(argv: Sequence[str], unit_dir: Path) -> list[list[str]]:
    """Args:
        argv: compose call of the infra stack.
        unit_dir: directory holding the units of :func:`idle_units`.

    Returns:
        The commands that link the service and enable the timer inside the runner.
    """
    systemctl = [*argv, "exec", "-T", SERVICE, "systemctl"]
    return [
        [*systemctl, "link", str(unit_dir / f"{TIMER}.service")],
        [*systemctl, "enable", "--now", str(unit_dir / f"{TIMER}.timer")],
    ]


def tools_commands(
    projects: Sequence[str], action: str, outer: Sequence[str]
) -> list[list[str]]:
    """Args:
        projects: compose projects of the tools roles inside the runner.
        action: one of TOOLS_ACTIONS.
        outer: compose call of the infra stack, or empty when already inside the runner.

    Returns:
        One command per project; the caches inside the runner stay untouched.

    Raises:
        ValueError: the action is not one of TOOLS_ACTIONS.
    """
    from cli.administration.deploy.development.stack import runner_compose_argv

    if action not in TOOLS_ACTIONS:
        raise ValueError(f"unknown tools action {action!r}")
    prefix = [*outer, "exec", "-T", SERVICE] if outer else []
    return [[*prefix, *runner_compose_argv(project, action)] for project in projects]


def addressable(
    projects: Sequence[str],
    outer: Sequence[str],
    output: Callable[[list[str]], str | None],
) -> dict[str, bool]:
    """Args:
        projects: compose projects of the tools roles inside the runner.
        outer: compose call of the infra stack.
        output: runs a command and returns its stdout, or None on failure.

    Returns:
        Per project, whether ``docker compose -p <project>`` lists a container of it.
    """
    from cli.administration.deploy.development.stack import runner_compose_argv

    found: dict[str, bool] = {}
    for project in projects:
        command = [
            *outer,
            "exec",
            "-T",
            SERVICE,
            *runner_compose_argv(project, "ps"),
            "--all",
            "--quiet",
        ]
        found[project] = bool((output(command) or "").strip())
    return found
