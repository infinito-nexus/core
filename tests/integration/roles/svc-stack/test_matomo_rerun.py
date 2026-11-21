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

from .test_front_batch_run import ALPHA, STACK, _build
from .test_stack_entry import _write

INJECTION = Path("roles/sys-front-inj-matomo") / ROLE_FILE_TASKS_MAIN
RERUN = Path("roles/web-app-matomo/tasks/08_reinject_consumers/batch.yml")

STUB_FRONT = """---
- name: Build the injection facts the way sys-front-inj-all does
  ansible.builtin.set_fact:
    inj_enabled: {matomo: true}

- name: Render the Matomo injection of the vhost
  ansible.builtin.include_role:
    name: sys-front-inj-matomo

- name: Record the front and whether it tracks
  ansible.builtin.set_fact:
    stub_events: "{{ stub_events + ['front:' ~ stack_batch_consumer ~ '|' ~ inj_enabled.matomo] }}"
"""

STUB_RESOLVE = """---
- name: Answer the site id the stub Matomo knows
  ansible.builtin.set_fact:
    matomo_site_id: "{{ stub_site_ids.get(application_id, '') }}"
"""

STUB_INJECT = """---
- name: Record the injection
  ansible.builtin.set_fact:
    stub_events: "{{ stub_events + ['inject:' ~ application_id ~ '|' ~ matomo_token_override] }}"
"""

PLAYBOOK = """---
- name: Render a first-deploy front batch, then let Matomo re-run it
  hosts: localhost
  gather_facts: false
  connection: local
  vars:
    stub_events: []
    front_proxy_batch_vhosts: {}
    matomo_token_override: ""
  handlers:
    - name: Record the reload
      listen: reload-openresty
      ansible.builtin.set_fact:
        stub_events: "{{ stub_events + ['reload'] }}"
  tasks:
    - name: Build the injection facts of a vhost outside any front batch
      ansible.builtin.set_fact:
        inj_enabled: {matomo: true}

    - name: Render a vhost outside any front batch without a site id
      ansible.builtin.include_role:
        name: sys-front-inj-matomo
      vars:
        application_id: web-app-plain
        stub_site_ids: {}

    - name: Serve the batch before Matomo knows the site
      ansible.builtin.include_role:
        name: svc-stack
        tasks_from: batch/serve.yml
      vars:
        stack_batch_items: "{{ stub_plan }}"
        stub_site_ids: {}

    - name: Keep the record the batch left
      ansible.builtin.set_fact:
        stub_recorded: "{{ stack_matomo_unsited | list }}"

    - name: Let Matomo re-run the fronts once it serves the site
      ansible.builtin.include_role:
        name: web-app-matomo
        tasks_from: 08_reinject_consumers/batch.yml
      vars:
        matomo_token_value: installed
        stub_site_ids: {web-app-alpha: "7"}

    - name: Report what happened
      ansible.builtin.copy:
        dest: "{{ report_out }}"
        content: >-
          {{ {'events': stub_events, 'recorded': stub_recorded,
              'left': stack_matomo_unsited | list} | to_json }}
        mode: "0644"
"""


def run_rerun() -> dict:
    """Returns:
        the events, the consumers the batch recorded and the record left
        after Matomo's re-run.

    Raises:
        RuntimeError: when ansible-playbook exits non-zero.
    """
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        _build(workdir, guard=False)
        _write(workdir / STACK / "tasks/batch/front.yml", STUB_FRONT)
        for path in (INJECTION, RERUN):
            _write(workdir / path, read_text(str(PROJECT_ROOT / path)))
        tasks = workdir / "roles/sys-front-inj-matomo/tasks"
        _write(tasks / "resolve_site.yml", STUB_RESOLVE)
        _write(tasks / "inject.yml", STUB_INJECT)
        _write(workdir / "play.yml", PLAYBOOK)
        report = workdir / "report.json"
        _write(
            workdir / "extra.json",
            json.dumps(
                {
                    "stub_plan": [ALPHA],
                    "IS_STACK_HOST": False,
                    "nest_late": False,
                    "report_out": str(report),
                }
            ),
        )
        env = {
            **os.environ,
            "ANSIBLE_ROLES_PATH": str(workdir / "roles"),
            "ANSIBLE_LOOKUP_PLUGINS": f"{workdir / 'lookup'}:{PROJECT_ROOT / 'plugins/lookup'}",
            "ANSIBLE_LIBRARY": str(workdir / "library"),
            "PATH": f"{workdir / 'bin'}:{os.environ['PATH']}",
            "STUB_PROBE_STATUS": json.dumps({}),
        }
        result = subprocess.run(
            [
                "ansible-playbook",
                "-i",
                str(workdir / "inventory.ini"),
                str(workdir / "play.yml"),
                "-e",
                f"@{workdir / 'extra.json'}",
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


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
class TestMatomoRerun(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.observed = run_rerun()

    def test_a_first_deploy_keeps_tracking_on_for_a_bridged_consumer(self) -> None:
        fronts = [
            event
            for event in self.observed["events"]
            if event.startswith(("front:", "inject:"))
        ]
        self.assertEqual(
            fronts,
            [
                "inject:web-app-plain|",
                "inject:web-app-alpha|",
                "front:web-app-alpha|True",
                "inject:web-app-alpha|installed",
                "front:web-app-alpha|True",
            ],
        )

    def test_only_a_batch_front_is_recorded_and_the_re_run_empties_the_record(
        self,
    ) -> None:
        self.assertEqual(self.observed["recorded"], ["web-app-alpha"])
        self.assertEqual(self.observed["left"], [])


if __name__ == "__main__":
    unittest.main()
