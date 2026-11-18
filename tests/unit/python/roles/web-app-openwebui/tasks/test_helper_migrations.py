from __future__ import annotations

import json
import unittest

import yaml

from . import PROJECT_ROOT

TASKS_DIR = PROJECT_ROOT / "roles/web-app-openwebui/tasks"
HELPER_FILES = {"admin.yml", "agent_models.yml", "mcp_grants.yml"}


def python_execs() -> dict[str, str]:
    """Collect every task that runs python3 inside the Open WebUI container.

    Returns:
        The serialised command of each such task, keyed by
        ``<file>: <task name>``.
    """
    found = {}
    for path in sorted(TASKS_DIR.rglob("*.yml")):
        for task in yaml.safe_load(path.read_text()) or []:
            for module in ("ansible.builtin.command", "ansible.builtin.shell"):
                command = json.dumps(task.get(module, ""))
                if "exec" in command and "python3" in command:
                    found[f"{path.name}: {task['name']}"] = command
    return found


class TestHelpersSkipMigrations(unittest.TestCase):
    def test_every_helper_file_is_scanned(self):
        scanned = {key.split(":", 1)[0] for key in python_execs()}
        self.assertEqual(HELPER_FILES - scanned, set())

    def test_every_python_exec_disables_migrations(self):
        missing = [
            key
            for key, command in python_execs().items()
            if "ENABLE_DB_MIGRATIONS=false" not in command
        ]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
