from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING, Any

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str

if TYPE_CHECKING:
    from pathlib import Path

ROLE = PROJECT_ROOT / "roles" / "web-app-homeassistant"
REALIGN = ROLE / "tasks" / "utils" / "owner" / "realign.yml"
RESOLVER = "roles/sys-svc-compose/tasks/utils/swarm/resolve_host_cid.yml"
PREFIX = "HOMEASSISTANT"


def load_tasks(path: Path) -> list[dict[str, Any]]:
    """Load a task file of the role.

    Args:
        path: the task file.

    Returns:
        Its task list.
    """
    return load_yaml_str(read_text(str(path))) or []


def included_file(task: dict[str, Any]) -> str:
    """Return the file a task includes.

    Args:
        task: one task of a task file.

    Returns:
        The ``include_tasks`` target, or ``""`` for any other task.
    """
    target = task.get("ansible.builtin.include_tasks", task.get("include_tasks"))
    if isinstance(target, dict):
        target = target.get("file")
    return str(target or "")


def resolves_the_hub(task: dict[str, Any]) -> bool:
    """Tell whether a task re-resolves the hub's node and container id.

    Args:
        task: one task of a task file.

    Returns:
        True when the task includes the shared resolver for ``PREFIX``,
        directly or through a task file of the role.
    """
    target = included_file(task)
    if RESOLVER in target:
        return (task.get("vars") or {}).get("resolve_output_prefix") == PREFIX
    local = re.fullmatch(r"\{\{\s*role_path\s*\}\}/(.+)", target)
    return local is not None and any(
        resolves_the_hub(inner) for inner in load_tasks(ROLE / local.group(1))
    )


class TestOwnerRealignResolvesRecreatedHub(unittest.TestCase):
    def test_the_check_after_the_recreation_targets_the_new_container(self) -> None:
        tasks = load_tasks(REALIGN)
        flush = next(
            index
            for index, task in enumerate(tasks)
            if task.get("ansible.builtin.meta", task.get("meta")) == "flush_handlers"
        )
        check = next(
            index
            for index, task in enumerate(tasks)
            if index > flush and included_file(task).endswith("owner/provision.yml")
        )
        self.assertTrue(
            any(resolves_the_hub(task) for task in tasks[flush + 1 : check]),
            "the container-recreate handler forces a new swarm task, so the "
            f"{PREFIX}_LOCAL_CID resolved before the flush names an exited "
            "container and the owner check fails with 'container ... is not "
            f"running'; resolve {PREFIX}_HOST_NODE and {PREFIX}_LOCAL_CID again "
            "between the flush and the check",
        )


if __name__ == "__main__":
    unittest.main()
