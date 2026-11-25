from __future__ import annotations

import unittest

from utils.cache import ROLES_DIR
from utils.cache.yaml import load_yaml_any

INPUTS = ROLES_DIR / "web-app-semaphore" / "tasks" / "utils" / "project" / "inputs.yml"
HOST_KEY = "{{ SEMAPHORE_APP_CONTROL_HOST_KEY_FILE }}"


def _position(tasks: list, match) -> int:
    """
    Args:
        tasks: the task list of inputs.yml.
        match: a predicate over one task.

    Returns:
        the index of the only task the predicate matches.
    """
    positions = [index for index, task in enumerate(tasks) if match(task)]
    if len(positions) != 1:
        raise AssertionError(f"expected one matching task in {INPUTS}, got {positions}")
    return positions[0]


class TestTheHostKeyIsReadOnlyAfterSshdIsUp(unittest.TestCase):
    def test_sshd_is_included_before_the_host_key_is_read(self) -> None:
        tasks = load_yaml_any(str(INPUTS))
        sshd = _position(
            tasks,
            lambda task: (
                task.get("ansible.builtin.include_role", {}).get("name")
                == "sys-svc-sshd"
            ),
        )
        host_key = _position(
            tasks,
            lambda task: task.get("ansible.builtin.slurp", {}).get("src") == HOST_KEY,
        )
        self.assertLess(sshd, host_key)
        self.assertNotIn(
            "SEMAPHORE_DEPLOY_FIXTURE_ENABLED", str(tasks[sshd].get("when", ""))
        )


if __name__ == "__main__":
    unittest.main()
