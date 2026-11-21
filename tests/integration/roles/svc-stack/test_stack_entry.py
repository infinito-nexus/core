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
from utils.roles.mapping import (
    ROLE_FILE_HANDLERS_MAIN,
    ROLE_FILE_TASKS_MAIN,
    ROLE_FILE_VARS_MAIN,
)

ENTRY = Path("tasks/utils/load/entry.yml")
ENTRY_FIRST = Path("tasks/utils/load/entry/first.yml")
ENTRY_BACK = Path("tasks/utils/load/entry/back.yml")
ENTRY_STEP = Path("tasks/utils/load/entry/step.yml")
STACK_VARS = Path("group_vars/all/24_stack.yml")
CANONICAL_BRIDGE = Path("roles/svc-stack/files/bridge.yml")
BRIDGED = ("web-app-alpha", "web-app-beta", "web-app-gamma", "web-app-delta")
GUARDED = ("web-app-beta", "web-app-delta")
STAGED = ("web-app-alpha", "web-app-beta", "web-app-delta")
PLAIN = "web-app-plain"

STUB_STAGE = """---
- name: Record the stage the entry ran
  ansible.builtin.set_fact:
    stub_runs: >-
      {{ stub_runs + [['stage', application_id, domain | default('none'),
                       consumer_scope] | join('|')] }}
"""

STUB_GUARD = """---
- name: Record the guard the entry ran
  ansible.builtin.set_fact:
    stub_runs: "{{ stub_runs + [['guard', application_id, consumer_scope] | join('|')] }}"

- name: Refuse the delta role
  ansible.builtin.assert:
    that:
      - application_id != 'web-app-delta'
    fail_msg: guard refused
"""

STUB_BACKEND = """---
- name: Record the backend the bridge reached
  ansible.builtin.set_fact:
    stub_runs: >-
      {{ stub_runs + [[stack_batch_consumer, application_id, domain | default('none'),
                       stack_batch_stage, consumer_scope] | join('|')] }}

- name: Load a handler role the way a backend loads sys-svc-compose
  ansible.builtin.include_role:
    name: handler-stub
  when: stack_batch_consumer == 'web-app-alpha'
"""

STUB_NOTIFY = """---
- name: Notify the handler the way a compose render does
  ansible.builtin.debug:
    msg: notify
  changed_when: true
  notify: stub poke
"""

STUB_HANDLER = """---
- name: Record that the handler ran
  listen: stub poke
  ansible.builtin.set_fact:
    stub_runs: "{{ stub_runs + ['handler|ran'] }}"
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
    - name: Mark the fronts of the beta and delta roles as served by the front batch
      ansible.builtin.set_fact:
        stack_front_served: {web-app-beta: true, web-app-delta: true}

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

    - name: Flush the handlers the backend notified, as the role body does after the entry
      ansible.builtin.meta: flush_handlers

    - name: Enter a bridged role without a domain
      ansible.builtin.include_tasks: "{{ entry_file }}"
      vars:
        entry_role: web-app-beta
        entry_application_id: web-app-beta
        entry_domain: false
        entry_post_run: false
      when: STACK_ENTRY_PENDING | bool

    - name: Enter a bridged role whose guard refuses it
      block:
        - name: Enter it
          ansible.builtin.include_tasks: "{{ entry_file }}"
          vars:
            entry_role: web-app-delta
            entry_application_id: web-app-delta
            entry_domain: false
            entry_post_run: false
          when: STACK_ENTRY_PENDING | bool
      rescue:
        - name: Record the refusal
          ansible.builtin.set_fact:
            stub_runs: "{{ stub_runs + ['refused|web-app-delta'] }}"

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


def write_entry_tree(workdir: Path) -> None:
    """Args:
    workdir: the playbook directory that receives the stack entry, the stack
        vars and the svc-stack stages the entry reaches, stubbed.
    """
    for path in (ENTRY, ENTRY_FIRST, ENTRY_BACK, ENTRY_STEP, STACK_VARS):
        _write(workdir / path, read_text(str(PROJECT_ROOT / path)))
    _write(workdir / "roles/svc-stack/tasks/batch/back.yml", STUB_BACKEND)
    _write(workdir / "roles/svc-stack/tasks/batch/late.yml", STUB_LATE)


def _build(workdir: Path) -> None:
    """Args:
    workdir: an empty directory that becomes the playbook directory.
    """
    write_entry_tree(workdir)
    _write(workdir / "roles/handler-stub" / ROLE_FILE_TASKS_MAIN, STUB_NOTIFY)
    _write(workdir / "roles/handler-stub" / ROLE_FILE_HANDLERS_MAIN, STUB_HANDLER)
    bridge = read_text(str(PROJECT_ROOT / CANONICAL_BRIDGE))
    for role in BRIDGED:
        _write(workdir / "roles" / role / "tasks/utils/stack.yml", bridge)
        _write(
            workdir / "roles" / role / ROLE_FILE_VARS_MAIN,
            f"---\nconsumer_scope: {role}-vars\n",
        )
    for role in GUARDED:
        _write(workdir / "roles" / role / "tasks/utils/stack/guard.yml", STUB_GUARD)
    for role in STAGED:
        _write(workdir / "roles" / role / "tasks/utils/stack/stage.yml", STUB_STAGE)
    _write(workdir / "roles" / PLAIN / ROLE_FILE_TASKS_MAIN, "---\n[]\n")
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
            [run for run in self.observed["runs"] if "|back|" in run],
            [
                "web-app-alpha|web-app-alpha|web-app-alpha.example|back|web-app-alpha-vars",
                "web-app-beta|web-app-beta|none|back|web-app-beta-vars",
            ],
        )

    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
    def test_only_an_unplanned_front_is_served_late_before_its_backend(self) -> None:
        self.assertEqual(
            self.observed["runs"][:3],
            [
                "late|web-app-alpha|web-app-alpha",
                "stage|web-app-alpha|web-app-alpha.example|web-app-alpha-vars",
                "web-app-alpha|web-app-alpha|web-app-alpha.example|back|web-app-alpha-vars",
            ],
        )
        self.assertEqual(
            [run for run in self.observed["runs"] if run.startswith("late|")],
            ["late|web-app-alpha|web-app-alpha"],
        )

    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
    def test_a_guard_runs_in_its_role_scope_before_the_backend_and_can_stop_it(
        self,
    ) -> None:
        self.assertEqual(
            [run for run in self.observed["runs"] if "web-app-beta" in run],
            [
                "guard|web-app-beta|web-app-beta-vars",
                "stage|web-app-beta|none|web-app-beta-vars",
                "web-app-beta|web-app-beta|none|back|web-app-beta-vars",
            ],
        )
        self.assertEqual(
            [run for run in self.observed["runs"] if "web-app-delta" in run],
            ["guard|web-app-delta|web-app-delta-vars", "refused|web-app-delta"],
        )

    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
    def test_a_stage_runs_once_in_its_role_scope_right_before_its_backend(
        self,
    ) -> None:
        runs = self.observed["runs"]
        stages = [run for run in runs if run.startswith("stage|")]
        self.assertEqual(
            stages,
            [
                "stage|web-app-alpha|web-app-alpha.example|web-app-alpha-vars",
                "stage|web-app-beta|none|web-app-beta-vars",
            ],
        )
        for stage in stages:
            app = stage.split("|")[1]
            self.assertTrue(runs[runs.index(stage) + 1].startswith(f"{app}|{app}|"))

    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
    def test_the_entered_map_keys_every_backend_that_ran(self) -> None:
        self.assertEqual(
            self.observed["entered"], {"web-app-alpha": True, "web-app-beta": True}
        )

    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
    def test_a_post_load_first_entry_is_refused(self) -> None:
        self.assertEqual(self.observed["refused"], "refused")

    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
    def test_a_handler_the_backend_loaded_still_runs_once_the_entry_is_recorded(
        self,
    ) -> None:
        runs = self.observed["runs"]
        back = (
            "web-app-alpha|web-app-alpha|web-app-alpha.example|back|web-app-alpha-vars"
        )
        self.assertEqual(runs[runs.index(back) + 1], "handler|ran")

    def test_the_entry_flushes_no_handlers(self) -> None:
        for path in (ENTRY, ENTRY_FIRST):
            with self.subTest(str(path)):
                text = json.dumps(load_yaml_any(str(PROJECT_ROOT / path)))
                self.assertNotIn("flush_handlers", text)


if __name__ == "__main__":
    unittest.main()
