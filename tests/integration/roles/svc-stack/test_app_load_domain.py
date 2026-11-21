from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

from utils.cache.files import PROJECT_ROOT, read_text
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN, ROLE_FILE_VARS_MAIN

from .test_stack_entry import CANONICAL_BRIDGE, _write, write_entry_tree

APP_LOAD = Path("tasks/utils/load/app.yml")
WITH_DOMAIN = "web-app-dom"
WITHOUT_DOMAIN = "svc-nodom"

STUB_DOMAINS_LOOKUP = f"""from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        return [{{"{WITH_DOMAIN}": ["{WITH_DOMAIN}.example"]}}]
"""

STUB_CARRIER = """from ansible.plugins.action import ActionBase


class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        return {"changed": False}
"""

PROBE = """---
- name: Record the domain the role body sees
  ansible.builtin.set_fact:
    body_domains: >-
      {{ body_domains | combine({application_id: domain if domain is defined else 'unbound'}) }}
"""

PLAYBOOK = """---
- name: Load roles the way nested application loads do
  hosts: localhost
  gather_facts: false
  connection: local
  vars:
    DEBUG: false
    stub_runs: []
    body_domains: {}
  tasks:
    - name: Load every role through utils/load/app.yml
      ansible.builtin.include_tasks: "{{ lookup('path_absolute', 'tasks/utils/load/app.yml') }}"
      loop: "{{ loaded_roles }}"
      loop_control:
        loop_var: load_app_id

    - name: Report what the backends and the bodies saw
      ansible.builtin.copy:
        dest: "{{ report_out }}"
        content: "{{ {'runs': stub_runs, 'bodies': body_domains} | to_json }}"
        mode: "0644"
"""


def _build(workdir: Path, app_load: str) -> None:
    """Args:
    workdir: an empty directory that becomes the playbook directory.
    app_load: the text of tasks/utils/load/app.yml under test.
    """
    _write(workdir / APP_LOAD, app_load)
    write_entry_tree(workdir)
    bridge = read_text(str(PROJECT_ROOT / CANONICAL_BRIDGE))
    for role in (WITH_DOMAIN, WITHOUT_DOMAIN):
        _write(workdir / "roles" / role / "tasks/utils/stack.yml", bridge)
        _write(workdir / "roles" / role / ROLE_FILE_TASKS_MAIN, PROBE)
        _write(
            workdir / "roles" / role / ROLE_FILE_VARS_MAIN,
            f"---\nconsumer_scope: {role}-vars\n",
        )
    _write(workdir / "lookup/domains.py", STUB_DOMAINS_LOOKUP)
    _write(workdir / "action/applications_carrier.py", STUB_CARRIER)
    _write(workdir / "play.yml", PLAYBOOK)


def run_app_load(app_load: str) -> dict:
    """Args:
        app_load: the text of tasks/utils/load/app.yml under test.

    Returns:
        the backend records and the domain every role body saw.

    Raises:
        RuntimeError: when ansible-playbook exits non-zero.
    """
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        _build(workdir, app_load)
        report = workdir / "report.json"
        env = {
            **os.environ,
            "ANSIBLE_ROLES_PATH": str(workdir / "roles"),
            "ANSIBLE_LOOKUP_PLUGINS": f"{workdir / 'lookup'}:{PROJECT_ROOT / 'plugins/lookup'}",
            "ANSIBLE_ACTION_PLUGINS": str(workdir / "action"),
        }
        result = subprocess.run(
            [
                "ansible-playbook",
                "-i",
                "localhost,",
                str(workdir / "play.yml"),
                "-e",
                f"report_out={report}",
                "-e",
                json.dumps({"loaded_roles": [WITH_DOMAIN, WITHOUT_DOMAIN]}),
            ],
            cwd=str(workdir),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"ansible-playbook failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )
        return json.loads(read_text(str(report)))


class TestAppLoadDomain(unittest.TestCase):
    observed: ClassVar[dict] = {}

    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("ansible-playbook"):
            cls.observed = run_app_load(read_text(str(PROJECT_ROOT / APP_LOAD)))

    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
    def test_only_a_role_with_a_domain_gets_one_bound(self) -> None:
        self.assertEqual(
            self.observed["bodies"],
            {WITH_DOMAIN: f"{WITH_DOMAIN}.example", WITHOUT_DOMAIN: "unbound"},
        )

    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
    def test_the_stack_backend_gets_the_same_binding(self) -> None:
        self.assertEqual(
            [run for run in self.observed["runs"] if not run.startswith("late|")],
            [
                f"{WITH_DOMAIN}|{WITH_DOMAIN}|{WITH_DOMAIN}.example|back|{WITH_DOMAIN}-vars",
                f"{WITHOUT_DOMAIN}|{WITHOUT_DOMAIN}|none|back|{WITHOUT_DOMAIN}-vars",
            ],
        )


if __name__ == "__main__":
    unittest.main()
