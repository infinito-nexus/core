from __future__ import annotations

import json
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

TASKS_DIR = PROJECT_ROOT / "roles/web-app-openwebui/tasks"
HELPER_FILES = {"admin.yml", "agent_models.yml", "mcp_grants.yml"}


def python_execs() -> dict[str, str]:
    """
    Returns:
        The serialised command of each such task, keyed by
        ``<file>: <task name>``.
    """
    found = {}
    paths = (Path(p) for p in iter_project_files(extensions=(".yml",)))
    for path in sorted(p for p in paths if p.is_relative_to(TASKS_DIR)):
        for task in load_yaml_any(str(path)) or []:
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
