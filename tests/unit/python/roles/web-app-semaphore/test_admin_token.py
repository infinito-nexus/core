from __future__ import annotations

import copy
import os
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text
from utils.cache.yaml import load_yaml_str

TASKS = PROJECT_ROOT / "roles" / "web-app-semaphore" / "tasks"
ADMIN = "utils/admin.yml"
MINT = "sql/project/prepare.sql.j2"
REVOKE = "sql/project/revoke.sql.j2"
CALLERS = {
    "workspace.yml": "utils/workspace/operation.yml",
    "workspace_stop.yml": "utils/workspace/stop.yml",
    "utils/project/converge.yml": "utils/project/sync.yml",
}


def task_files():
    """Returns:
    ``{path below tasks/: parsed tasks}`` of every task file of the role.
    """
    prefix = f"{TASKS}{os.sep}"
    files = sorted(
        Path(path)
        for path in iter_project_files(extensions=(".yml",))
        if path.startswith(prefix)
    )
    return {
        str(path.relative_to(TASKS)): load_yaml_str(read_text(str(path))) or []
        for path in files
    }


def walk(tasks):
    for task in tasks or []:
        yield task
        for key in ("block", "rescue", "always"):
            yield from walk(task.get(key))


def token_findings(files):
    """Args:
        files: as :func:`task_files` returns them.

    Returns:
        One message per task file that mints or revokes the admin API token
        outside ``utils/admin.yml``, per caller that does not hand its steps to
        that util, and when the util does not revoke in the always of the steps.
    """
    findings = [
        f"{name} mints or revokes the admin API token"
        for name, tasks in sorted(files.items())
        if name != ADMIN and (MINT in str(tasks) or REVOKE in str(tasks))
    ]
    for caller, steps in sorted(CALLERS.items()):
        handed = [
            task["vars"]["semaphore_admin_tasks"]
            for task in walk(files[caller])
            if str(task.get("ansible.builtin.include_tasks", "")).endswith(ADMIN)
        ]
        if handed != [f"{{{{ role_path }}}}/tasks/{steps}"]:
            findings.append(f"{caller} hands the admin util {handed}")
    guarded = [
        task
        for task in files[ADMIN]
        if "semaphore_admin_tasks" in str(task.get("block"))
        and REVOKE in str(task.get("always"))
        and REVOKE not in str(task["block"])
    ]
    if len(guarded) != 1:
        findings.append(f"{ADMIN} revokes the token outside the always of its steps")
    return findings


class TestAdminToken(unittest.TestCase):
    def setUp(self):
        self.files = task_files()

    def test_one_util_mints_and_revokes_the_token_for_every_caller(self):
        self.assertEqual(token_findings(self.files), [])

    def test_negative_control_an_inline_mint_in_a_caller_fails(self):
        planted = copy.deepcopy(self.files)
        mint = next(t for t in planted[ADMIN] if MINT in str(t))
        planted["utils/project/converge.yml"][0] = mint
        self.assertEqual(
            token_findings(planted),
            [
                "utils/project/converge.yml mints or revokes the admin API token",
                "utils/project/converge.yml hands the admin util []",
            ],
        )

    def test_negative_control_a_revoke_after_the_steps_fails(self):
        planted = copy.deepcopy(self.files)
        guarded = next(t for t in planted[ADMIN] if "always" in t)
        guarded["block"] += guarded.pop("always")
        self.assertEqual(
            token_findings(planted),
            [f"{ADMIN} revokes the token outside the always of its steps"],
        )


if __name__ == "__main__":
    unittest.main()
