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
from utils.cache.yaml import load_yaml_any

ENTRY = Path("tasks/utils/load/entry.yml")
ENTRY_BACK = Path("tasks/utils/load/entry/back.yml")
STACK_VARS = Path("group_vars/all/24_stack.yml")
CANONICAL_BRIDGE = Path("roles/svc-stack/files/bridge.yml")
BRIDGED = ("web-app-alpha", "web-app-beta", "web-app-gamma")
PLAIN = "web-app-plain"

STUB_BACKEND = """---
- name: Record the backend the bridge reached
  ansible.builtin.set_fact:
    stub_runs: >-
      {{ stub_runs + [[stack_batch_consumer, application_id, domain | default('none'),
                       stack_batch_stage, consumer_scope] | join('|')] }}
"""

STUB_LATE = """---
- name: Record the late front the entry asked for
  ansible.builtin.set_fact:
    stub_runs: "{{ stub_runs + [['late', stack_late_application_id, stack_late_role] | join('|')] }}"
    stack_front_served: "{{ stack_front_served | combine({stack_late_application_id: true}) }}"
"""

STUB_DOMAIN_LOOKUP = """from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        return [f"{terms[0]}.example"]
"""

PLAYBOOK = """---
- name: Drive the stack entry the way the loader sites do
  hosts: localhost
  gather_facts: false
  connection: local
  vars:
    stub_runs: []
    entry_file: "{{ lookup('path_absolute', 'tasks/utils/load/entry.yml') }}"
  tasks:
    - name: Mark the front of the beta role as served by the front batch
      ansible.builtin.set_fact:
        stack_front_served: {web-app-beta: true}

    - name: Enter a bridged role twice with its domain
      ansible.builtin.include_tasks: "{{ entry_file }}"
      loop: [1, 2]
      loop_control:
        loop_var: entry_round
      vars:
        entry_role: web-app-alpha
        entry_application_id: web-app-alpha
        entry_domain: true
        entry_post_run: false
      when: STACK_ENTRY_PENDING | bool

    - name: Enter a bridged role without a domain
      ansible.builtin.include_tasks: "{{ entry_file }}"
      vars:
        entry_role: web-app-beta
        entry_application_id: web-app-beta
        entry_domain: false
        entry_post_run: false
      when: STACK_ENTRY_PENDING | bool

    - name: Enter a role without a bridge on a post-load path
      ansible.builtin.include_tasks: "{{ entry_file }}"
      vars:
        entry_role: web-app-plain
        entry_application_id: web-app-plain
        entry_domain: false
        entry_post_run: true
      when: STACK_ENTRY_PENDING | bool

    - name: Enter an entered bridged role on a post-load path
      ansible.builtin.include_tasks: "{{ entry_file }}"
      vars:
        entry_role: web-app-alpha
        entry_application_id: web-app-alpha
        entry_domain: false
        entry_post_run: true
      when: STACK_ENTRY_PENDING | bool

    - name: First-enter a bridged role on a post-load path
      block:
        - name: Enter it
          ansible.builtin.include_tasks: "{{ entry_file }}"
          vars:
            entry_role: web-app-gamma
            entry_application_id: web-app-gamma
            entry_domain: false
            entry_post_run: true
          when: STACK_ENTRY_PENDING | bool

        - name: Record that it passed
          ansible.builtin.copy:
            dest: "{{ refused_out }}"
            content: passed
            mode: "0644"
      rescue:
        - name: Record that it was refused
          ansible.builtin.copy:
            dest: "{{ refused_out }}"
            content: refused
            mode: "0644"

    - name: Report the backends and the entered map
      ansible.builtin.copy:
        dest: "{{ runs_out }}"
        content: "{{ {'runs': stub_runs, 'entered': stack_backend_entered} | to_json }}"
        mode: "0644"
"""


def _write(path: Path, body: str) -> None:
    """Args:
    path: the file to create, parents included.
    body: its text.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _build(workdir: Path) -> None:
    """Args:
    workdir: an empty directory that becomes the playbook directory.
    """
    for path in (ENTRY, ENTRY_BACK, STACK_VARS):
        _write(workdir / path, read_text(str(PROJECT_ROOT / path)))
    _write(workdir / "roles/svc-stack/tasks/batch/back.yml", STUB_BACKEND)
    _write(workdir / "roles/svc-stack/tasks/batch/late.yml", STUB_LATE)
    bridge = read_text(str(PROJECT_ROOT / CANONICAL_BRIDGE))
    for role in BRIDGED:
        _write(workdir / "roles" / role / "tasks/utils/stack.yml", bridge)
        _write(
            workdir / "roles" / role / "vars/main.yml",
            f"---\nconsumer_scope: {role}-vars\n",
        )
    _write(workdir / "roles" / PLAIN / "tasks/main.yml", "---\n[]\n")
    _write(workdir / "lookup/domain.py", STUB_DOMAIN_LOOKUP)
    _write(workdir / "play.yml", PLAYBOOK)


def _run(workdir: Path) -> tuple[dict, str]:
    """Args:
        workdir: the directory ``_build`` filled.

    Returns:
        the reported backends and entered map, and the post-load outcome.

    Raises:
        RuntimeError: when ansible-playbook exits non-zero.
    """
    env = {
        **os.environ,
        "ANSIBLE_ROLES_PATH": str(workdir / "roles"),
        "ANSIBLE_LOOKUP_PLUGINS": f"{workdir / 'lookup'}:{PROJECT_ROOT / 'plugins/lookup'}",
    }
    runs, refused = workdir / "runs.json", workdir / "refused.txt"
    result = subprocess.run(
        [
            "ansible-playbook",
            "-i",
            "localhost,",
            str(workdir / "play.yml"),
            "-e",
            f"runs_out={runs}",
            "-e",
            f"refused_out={refused}",
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
    return json.loads(read_text(str(runs))), read_text(str(refused))


class TestStackEntry(unittest.TestCase):
    observed: ClassVar[dict] = {}

    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("ansible-playbook"):
            return
        with tempfile.TemporaryDirectory() as tmp:
            _build(Path(tmp))
            report, refused = _run(Path(tmp))
        cls.observed = {**report, "refused": refused}

    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
    def test_each_bridged_role_runs_its_backend_once_in_its_own_scope(self) -> None:
        self.assertEqual(
            [run for run in self.observed["runs"] if not run.startswith("late|")],
            [
                "web-app-alpha|web-app-alpha|web-app-alpha.example|back|web-app-alpha-vars",
                "web-app-beta|web-app-beta|none|back|web-app-beta-vars",
            ],
        )

    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
    def test_only_an_unplanned_front_is_served_late_before_its_backend(self) -> None:
        self.assertEqual(
            self.observed["runs"][:2],
            [
                "late|web-app-alpha|web-app-alpha",
                "web-app-alpha|web-app-alpha|web-app-alpha.example|back|web-app-alpha-vars",
            ],
        )
        self.assertEqual(
            [run for run in self.observed["runs"] if run.startswith("late|")],
            ["late|web-app-alpha|web-app-alpha"],
        )

    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
    def test_the_entered_map_keys_every_backend_that_ran(self) -> None:
        self.assertEqual(
            self.observed["entered"], {"web-app-alpha": True, "web-app-beta": True}
        )

    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
    def test_a_post_load_first_entry_is_refused(self) -> None:
        self.assertEqual(self.observed["refused"], "refused")

    def test_the_entry_flushes_no_handlers(self) -> None:
        text = json.dumps(load_yaml_any(str(PROJECT_ROOT / ENTRY)))
        self.assertNotIn("flush_handlers", text)


if __name__ == "__main__":
    unittest.main()
