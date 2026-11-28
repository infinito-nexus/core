from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

from .test_stack_entry import _write

CORE = Path("roles/svc-stack/tasks/00_core.yml")
REAL = (
    CORE,
    Path("roles/svc-stack/tasks/batch/serve.yml"),
    Path("tasks/utils/once/flag.yml"),
    Path("group_vars/all/24_stack.yml"),
)

STUB_PLAN_LOOKUP = """import json
import os

from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        return [json.loads(os.environ["STUB_PLAN"])]
"""

PLAYBOOK = """---
- name: Run the front batch plan gate of svc-stack
  hosts: localhost
  gather_facts: false
  connection: local
  roles:
    - role: svc-stack
"""


def run_gate(planned: list[dict]) -> subprocess.CompletedProcess:
    """Args:
        planned: the plan the stubbed stack_batch lookup returns.

    Returns:
        the finished ansible-playbook run.
    """
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        _write(
            workdir / "roles/svc-stack" / ROLE_FILE_TASKS_MAIN,
            "---\n- include_tasks: 00_core.yml\n",
        )
        for path in REAL:
            _write(workdir / path, read_text(str(PROJECT_ROOT / path)))
        _write(workdir / "lookup/stack_batch.py", STUB_PLAN_LOOKUP)
        _write(workdir / "play.yml", PLAYBOOK)
        env = {
            **os.environ,
            "ANSIBLE_ROLES_PATH": str(workdir / "roles"),
            "ANSIBLE_LOOKUP_PLUGINS": str(workdir / "lookup"),
            "STUB_PLAN": json.dumps(planned),
        }
        return subprocess.run(
            ["ansible-playbook", "-i", "localhost,", str(workdir / "play.yml")],
            cwd=str(workdir),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
class TestBatchPlanGate(unittest.TestCase):
    def test_an_empty_plan_passes(self) -> None:
        self.assertEqual(run_gate([]).returncode, 0)

    def test_every_bad_role_is_named_at_once(self) -> None:
        result = run_gate(
            [
                {"id": "web-app-bad", "errors": ["bridge differs"]},
                {"id": "web-app-good", "errors": []},
                {"id": "web-svc-worse", "errors": ["meta does not parse"]},
            ]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("web-app-bad: bridge differs", result.stdout)
        self.assertIn("web-svc-worse: meta does not parse", result.stdout)
        self.assertNotIn("web-app-good:", result.stdout)


if __name__ == "__main__":
    unittest.main()
