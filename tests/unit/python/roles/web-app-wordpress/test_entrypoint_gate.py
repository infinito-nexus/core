from __future__ import annotations

import unittest

from jinja2 import Environment, select_autoescape

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

TASK_FILE = PROJECT_ROOT / "roles/web-app-wordpress/tasks/07_manager_ops.yml"
SHELL_KEYS = ("ansible.builtin.shell", "shell")


def command_text(task: dict) -> str:
    """
    Args:
        task: one parsed Ansible task.

    Returns:
        The shell command of the task, or an empty string for a task without one.
    """
    shell = next((task[key] for key in SHELL_KEYS if key in task), "")
    return shell["cmd"] if isinstance(shell, dict) else shell


def gate_passes(task: dict, pid1_comm: str) -> bool:
    """
    Args:
        task: the gate task with its ``register`` and ``until``.
        pid1_comm: what ``cat /proc/1/comm`` printed inside the container.

    Returns:
        Whether the task's ``until`` stops retrying on that output.
    """
    environment = Environment(autoescape=select_autoescape(default_for_string=False))
    expression = environment.compile_expression(task["until"])
    return bool(expression(**{task["register"]: {"stdout": pid1_comm, "rc": 0}}))


class TestEntrypointGate(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks = load_yaml_any(str(TASK_FILE), default_if_missing=[])
        self.first_exec = next(
            index
            for index, task in enumerate(self.tasks)
            if "container exec" in command_text(task)
        )

    def test_first_container_exec_waits_for_apache_as_pid1(self) -> None:
        gate = self.tasks[self.first_exec]
        self.assertIn("/proc/1/comm", command_text(gate))
        self.assertTrue(gate_passes(gate, "apache2\n"))
        for still_starting in (
            "",
            "with-ca-trust.s\n",
            "docker-entrypoi\n",
            "apache2-foregro\n",
        ):
            with self.subTest(pid1_comm=still_starting):
                self.assertFalse(gate_passes(gate, still_starting))

    def test_config_patch_and_install_run_after_the_gate(self) -> None:
        included = [
            index
            for index, task in enumerate(self.tasks)
            if task.get("include_tasks") in ("01_patch_config.yml", "02_install.yml")
        ]
        self.assertEqual(len(included), 2)
        self.assertTrue(all(index > self.first_exec for index in included))


if __name__ == "__main__":
    unittest.main()
