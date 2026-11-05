from pathlib import Path

from utils.cache.yaml import load_yaml_any

PROJECT_ROOT: Path = Path(__file__).resolve().parents[5]
ROLE: Path = PROJECT_ROOT / "roles" / "test-e2e-playwright"


def role_task(task_file: str, prefix: str) -> dict:
    """Find a task of the Playwright role by the start of its name.

    Args:
        task_file: path of the task file below the role's ``tasks`` directory.
        prefix: the start of the task name, usually its emoji.

    Returns:
        The first matching task, searched depth first through ``block``,
        ``rescue`` and ``always``.
    """
    pending = list(
        load_yaml_any(str(ROLE / "tasks" / task_file), default_if_missing=[])
    )
    while pending:
        task = pending.pop(0)
        if task.get("name", "").startswith(prefix):
            return task
        pending[:0] = (
            task.get("block", []) + task.get("rescue", []) + task.get("always", [])
        )
    raise LookupError(f"{task_file}: no task named {prefix}")
