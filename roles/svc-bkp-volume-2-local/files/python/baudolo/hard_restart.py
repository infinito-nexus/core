from __future__ import annotations

from pathlib import Path


def without_hard_restart(command: list[str]) -> list[str]:
    """Return ``command`` without --hard-restart-projects and its values.

    The flag exists for compose stacks whose database cannot be backed up hot,
    which is exactly what a snapshot removes, so the restart of a large stack
    would be paid for nothing. baudolo 3.2.1 rejects the combination outright.
    """
    if "--hard-restart-projects" not in command:
        return command
    start = command.index("--hard-restart-projects")
    end = start + 1
    while end < len(command) and not command[end].startswith("--"):
        end += 1
    return command[:start] + command[end:]


def paused(project_dir: Path, state_file: str) -> bool:
    """Return whether app-control paused the compose project in ``project_dir``.

    Args:
        project_dir: the compose project directory.
        state_file: the name of the app-control state marker inside it.
    """
    marker = project_dir / state_file
    return marker.is_file() and marker.read_text(encoding="utf-8").strip() == "stopped"


def without_paused_projects(command: list[str], state_file: str) -> list[str]:
    """Return ``command`` without the paused projects of --hard-restart-projects.

    Args:
        command: the baudolo command line, carrying --compose-dir.
        state_file: the name of the app-control state marker inside a project.
    """
    if "--hard-restart-projects" not in command:
        return command
    compose_dir = Path(command[command.index("--compose-dir") + 1])
    start = command.index("--hard-restart-projects") + 1
    end = start
    while end < len(command) and not command[end].startswith("--"):
        end += 1
    kept = [
        project
        for project in command[start:end]
        if not paused(compose_dir / project, state_file)
    ]
    if not kept:
        return without_hard_restart(command)
    return command[:start] + kept + command[end:]
