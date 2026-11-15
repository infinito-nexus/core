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

REAL = (
    Path("tasks/utils/sync/front.yml"),
    Path("tasks/utils/load/entry.yml"),
    Path("tasks/utils/load/entry/first.yml"),
    Path("tasks/utils/load/entry/back.yml"),
    Path("group_vars/all/24_stack.yml"),
    Path("roles/sys-service-loader/tasks/drain.yml"),
    Path("roles/sys-service-loader/tasks/list_or_shoot.yml"),
)

STUB_LATE = """---
- name: Record the one-item front batch
  ansible.builtin.set_fact:
    stub_events: "{{ stub_events + ['late:' ~ stack_late_application_id ~ '|' ~ stack_late_role] }}"

- name: Ask for the reload the front needs
  ansible.builtin.command:
    cmd: "true"
  changed_when: true
  notify: stub-reload

- name: Route a health check the way a front dependency does
  ansible.builtin.include_role:
    name: sys-service-loader
    tasks_from: list_or_shoot.yml
  vars:
    list_or_shoot_roles: [sys-stub-post]
"""

STUB_POST = """---
- name: Record the post-load role and the context it runs in
  ansible.builtin.set_fact:
    stub_events: "{{ stub_events + ['post:' ~ (service_loader_preloading | string)] }}"
"""

PLAYBOOK = """---
- name: Serve the front of a synced role the way utils/sync/role.yml does
  hosts: localhost
  gather_facts: false
  connection: local
  vars:
    stub_events: []
  handlers:
    - name: Record the early handler
      listen: stub-early
      ansible.builtin.set_fact:
        stub_events: "{{ stub_events + ['early'] }}"

    - name: Record the reload
      listen: stub-reload
      ansible.builtin.set_fact:
        stub_events: "{{ stub_events + ['reload'] }}"
  tasks:
    - name: Leave a handler pending from before the sync front
      ansible.builtin.command:
        cmd: "true"
      changed_when: true
      notify: stub-early

    - name: Serve the front of the synced role
      ansible.builtin.include_tasks: "{{ lookup('path_absolute', 'tasks/utils/sync/front.yml') }}"
      vars:
        sync_application_id: web-app-alpha

    - name: Report the events and the context left behind
      ansible.builtin.copy:
        dest: "{{ report_out }}"
        content: >-
          {{ {'events': stub_events, 'preloading': service_loader_preloading,
              'queued': service_loader_post_run} | to_json }}
        mode: "0644"
"""


def run_sync_front() -> dict:
    """Returns:
        the events of the sync front in order, the preload flag and the
        post-load queue it leaves behind.

    Raises:
        RuntimeError: when ansible-playbook exits non-zero.
    """
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        for path in REAL:
            _write(workdir / path, read_text(str(PROJECT_ROOT / path)))
        _write(workdir / "roles/svc-stack/tasks/batch/late.yml", STUB_LATE)
        _write(workdir / "roles/sys-stub-post" / ROLE_FILE_TASKS_MAIN, STUB_POST)
        _write(workdir / "play.yml", PLAYBOOK)
        report = workdir / "report.json"
        result = subprocess.run(
            [
                "ansible-playbook",
                "-i",
                "localhost,",
                str(workdir / "play.yml"),
                "-e",
                f"report_out={report}",
            ],
            cwd=str(workdir),
            env={
                **os.environ,
                "ANSIBLE_ROLES_PATH": str(workdir / "roles"),
                "ANSIBLE_LOOKUP_PLUGINS": str(PROJECT_ROOT / "plugins/lookup"),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"ansible-playbook failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )
        return json.loads(read_text(str(report)))


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
class TestSyncFront(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.observed = run_sync_front()

    def test_the_front_runs_between_two_flushes_and_queues_its_post_load_roles(
        self,
    ) -> None:
        self.assertEqual(
            self.observed["events"],
            ["early", "late:web-app-alpha|web-app-alpha", "reload", "post:False"],
        )

    def test_the_drain_closes_the_preload_context(self) -> None:
        self.assertFalse(self.observed["preloading"])
        self.assertEqual(self.observed["queued"], ["sys-stub-post"])


if __name__ == "__main__":
    unittest.main()
