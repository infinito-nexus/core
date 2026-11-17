from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

from utils.cache.files import read_text
from utils.cache.yaml import dump_yaml, load_yaml_any
from utils.roles.invocations import iter_tasks

from . import PROJECT_ROOT

TASKS = PROJECT_ROOT / "roles" / "test-e2e-playwright" / "tasks" / "03_run_pass.yml"
BUDGET = 10
COMMANDS = {
    "pass": ["sh", "-c", "echo out; echo err >&2"],
    "fail": ["sh", "-c", "echo out; echo err >&2; exit 1"],
    "kill": ["sleep", "15"],
}
SYNC = "sync-"
WAIT_BANNER = "TASK [⏳ Wait for the Playwright run to finish, web-app-x]"
REPORT = {
    "name": "Keep what 04_collect.yml reads of the run",
    "ansible.builtin.copy": {
        "dest": "{{ work }}/{{ inventory_hostname }}.json",
        "mode": "0644",
        "content": (
            "{{ {'rc': _playwright_run.rc | default('absent'),"
            " 'stdout': _playwright_run.stdout | default('absent'),"
            " 'stderr': _playwright_run.stderr | default('absent'),"
            " 'msg': _playwright_run.msg | default('absent')} | to_json }}"
        ),
    },
}
SYNC_RUN = {
    "name": "Run the command as the role ran it before, a synchronous task with a timeout",
    "ansible.builtin.command": {"argv": "{{ _command }}"},
    "timeout": "{{ TEST_E2E_PLAYWRIGHT_RUN_BUDGET | int }}",
    "register": "_playwright_run",
    "changed_when": False,
    "failed_when": False,
}


def role_task(prefix: str) -> dict:
    """Return the run pass task whose name starts with ``prefix``.

    Args:
        prefix: the start of the task name.
    """
    tasks = load_yaml_any(str(TASKS), default_if_missing=[])
    return next(t for t in iter_tasks(tasks) if t.get("name", "").startswith(prefix))


def _run(work: Path) -> tuple[str, dict[str, dict]]:
    """Run the role's serial pass tasks and the synchronous task they replace.

    Args:
        work: an empty directory for the inventory, play and reports.

    Returns:
        The playbook output and, per host that reached it, what 04_collect.yml
        reads of ``_playwright_run``.
    """
    run = dict(role_task("▶️ Run Playwright container"))
    del run["environment"]
    run["ansible.builtin.command"] = {"argv": "{{ _command }}"}
    variables = {
        "work": str(work),
        "application_id": "web-app-x",
        "TEST_E2E_PLAYWRIGHT_RUN_BUDGET": BUDGET,
        "TEST_E2E_PLAYWRIGHT_RUN_POLL_DELAY": 1,
    }
    hosts = {**COMMANDS, **{SYNC + mode: argv for mode, argv in COMMANDS.items()}}
    dump_yaml(
        work / "inventory.yml",
        {
            "all": {
                "hosts": {name: {"_command": argv} for name, argv in hosts.items()},
                "vars": {
                    "ansible_connection": "local",
                    "ansible_python_interpreter": sys.executable,
                },
            }
        },
    )
    dump_yaml(
        work / "play.yml",
        [
            {
                "name": "The role's serial pass",
                "hosts": ":".join(COMMANDS),
                "gather_facts": False,
                "vars": variables,
                "tasks": [run, role_task("⏳ Wait for the Playwright run"), REPORT],
            },
            {
                "name": "The synchronous pass it replaced",
                "hosts": ":".join(SYNC + mode for mode in COMMANDS),
                "gather_facts": False,
                "vars": variables,
                "tasks": [SYNC_RUN, REPORT],
            },
        ],
    )
    env = dict(os.environ)
    env.update(
        {
            "ANSIBLE_CONFIG": str(PROJECT_ROOT / "ansible.cfg"),
            "ANSIBLE_LOCAL_TEMP": str(work / "ansible-local"),
            "ANSIBLE_REMOTE_TEMP": str(work / "ansible-remote"),
            "ANSIBLE_ASYNC_DIR": str(work / "ansible-async"),
            "ANSIBLE_FORKS": str(len(hosts)),
            "ANSIBLE_NOCOLOR": "1",
        }
    )
    result = subprocess.run(
        [
            "ansible-playbook",
            "-i",
            str(work / "inventory.yml"),
            str(work / "play.yml"),
        ],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    reports = {
        name: json.loads(read_text(str(work / f"{name}.json")))
        for name in hosts
        if (work / f"{name}.json").is_file()
    }
    return result.stdout + result.stderr, reports


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook is required")
class TestSerialPassBudget(unittest.TestCase):
    output: ClassVar[str] = ""
    reports: ClassVar[dict[str, dict]] = {}

    @classmethod
    def setUpClass(cls) -> None:
        work = tempfile.TemporaryDirectory(prefix="playwright_budget_")
        cls.addClassCleanup(work.cleanup)
        cls.output, cls.reports = _run(Path(work.name))

    def test_a_passing_run_reports_what_the_synchronous_task_reported(self):
        self.assertEqual(self.reports["pass"], self.reports[SYNC + "pass"])
        self.assertEqual(
            (self.reports["pass"]["rc"], self.reports["pass"]["stdout"]), (0, "out")
        )

    def test_a_failing_run_reports_what_the_synchronous_task_reported(self):
        self.assertEqual(self.reports["fail"], self.reports[SYNC + "fail"])
        self.assertEqual(
            (self.reports["fail"]["rc"], self.reports["fail"]["stderr"]), (1, "err")
        )

    def test_a_run_past_its_budget_fails_loudly_with_its_role_named(self):
        for host in "kill", SYNC + "kill":
            with self.subTest(host=host):
                self.assertNotIn(host, self.reports)
                self.assertIn(f"fatal: [{host}]", self.output)
        self.assertGreater(
            self.output.index("fatal: [kill]"), self.output.index(WAIT_BANNER)
        )
        self.assertIn("Timeout exceeded", self.output)
        for host in "pass", "fail":
            with self.subTest(host=host):
                self.assertNotIn(f"fatal: [{host}]", self.output)
