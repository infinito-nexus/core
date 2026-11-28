from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text
from utils.roles.mapping import ROLE_FILE_DEFAULTS_MAIN, ROLE_FILE_VARS_MAIN

from .test_stack_entry import CANONICAL_BRIDGE, _write

STACK = Path("roles/svc-stack")
REAL = (
    STACK / "tasks/batch/serve.yml",
    STACK / "tasks/batch/late.yml",
    STACK / "tasks/batch/run.yml",
    STACK / "tasks/batch/warm.yml",
    STACK / ROLE_FILE_DEFAULTS_MAIN,
    STACK / "filter_plugins/front_proxy_batch.py",
    STACK / "filter_plugins/front_proxy_unserved.py",
    Path("tasks/utils/once/flag.yml"),
    Path("group_vars/all/24_stack.yml"),
)
WARM = (
    ("sys-svc-webserver-https", "main.yml"),
    ("sys-svc-container", "main.yml"),
    ("sys-svc-webserver-core", "main.yml"),
    ("sys-svc-certs", "once.yml"),
    ("sys-ctl-mtn-cert-renew", "main.yml"),
    ("sys-svc-nss", "main.yml"),
    ("sys-stk-front-base", "once.yml"),
)
ALPHA = {
    "id": "web-app-alpha",
    "role": "web-app-alpha",
    "phase": "server",
    "tls_mode": "letsencrypt",
    "errors": [],
}
BETA = {
    "id": "web-svc-beta",
    "role": "web-svc-beta",
    "phase": "preload",
    "tls_mode": "off",
    "errors": [],
}
LATE = {
    "id": "web-app-alpha",
    "role": "web-app-alpha",
    "phase": "late",
    "tls_mode": "letsencrypt",
    "errors": [],
}
NESTED = {
    "id": "web-svc-nested",
    "role": "web-svc-nested",
    "phase": "late",
    "tls_mode": "off",
    "errors": [],
}

STUB_WARM = """---
- name: Record the warm-up
  ansible.builtin.set_fact:
    stub_events: "{{ stub_events + ['warm:' ~ role_name] }}"

- include_tasks: utils/once/flag.yml
"""

STUB_FRONT_BASE = """---
- name: Record the warm-up
  ansible.builtin.set_fact:
    stub_events: "{{ stub_events + ['warm:' ~ role_name] }}"

- name: Enter a bridged role the plan does not hold, the way a flag-driven load does
  ansible.builtin.include_role:
    name: svc-stack
    tasks_from: batch/late.yml
  vars:
    stack_late_application_id: web-svc-nested
    stack_late_role: web-svc-nested
  when: nest_late | bool

- include_tasks: utils/once/flag.yml
"""

STUB_LATE_LOOKUP = """from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        return [[{"id": terms[0], "role": kwargs["role"], "phase": "late",
                  "tls_mode": "off", "errors": []}]]
"""

STUB_FRONT = """---
- name: Record the front the batch rendered
  ansible.builtin.set_fact:
    stub_events: >-
      {{ stub_events + ['front:' ~ ([stack_batch_consumer, application_id, stack_batch_stage,
                                     stack_front_phase, consumer_scope] | join('|'))] }}
    front_proxy_batch_vhosts: >-
      {{ front_proxy_batch_vhosts | combine({stack_batch_consumer ~ '.example':
           {'consumer': stack_batch_consumer, 'changed': true,
            'probe': {'url': 'https://' ~ stack_batch_consumer ~ '.example/', 'status_codes': [200]}}}) }}

- name: Ask for the reload the render needs
  ansible.builtin.command:
    cmd: "true"
  changed_when: true
  notify: reload-openresty
"""

STUB_GUARD = """---
- name: Record the guard the batch ran
  ansible.builtin.set_fact:
    stub_events: >-
      {{ stub_events + ['guard:' ~ ([stack_batch_consumer, application_id, consumer_scope] | join('|'))] }}

- name: Refuse the role when the test asks for it
  ansible.builtin.assert:
    that:
      - not (refuse_guard | bool)
    fail_msg: "guard refused {{ application_id }}"
"""

STUB_LOOKUP = """from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        return [{RESULT}]
"""

STUB_PROBE = """import json
import os

from ansible.module_utils.basic import AnsibleModule


def main():
    module = AnsibleModule(
        argument_spec={key: {"type": "raw"} for key in (
            "urls", "method", "status_codes", "attempts", "delay", "timeout",
            "validate_certs", "follow_redirects", "workers")},
    )
    answers = json.loads(os.environ["STUB_PROBE_STATUS"])
    module.exit_json(changed=False, status={name: answers[name] for name in module.params["urls"]})


main()
"""

STUB_CONTAINER = """#!/bin/sh
echo "$*" >> "$STUB_CONTAINER_LOG"
printf '%s\\n' "$STUB_TEST_STDERR" >&2
exit "$STUB_TEST_RC"
"""

PLAYBOOK = """---
- name: Run the front batch of svc-stack against stub dependencies
  hosts: localhost
  gather_facts: false
  connection: local
  vars:
    stub_events: []
    front_proxy_batch_vhosts: {}
  handlers:
    - name: Reload the stub OpenResty
      listen: reload-openresty
      ansible.builtin.command:
        cmd: "true"
      register: openresty_reload
      changed_when: reload_changed | bool

    - name: Record the reload
      listen: reload-openresty
      ansible.builtin.set_fact:
        stub_events: "{{ stub_events + ['reload'] }}"

    - name: Record the restart
      listen: restart-openresty
      ansible.builtin.set_fact:
        stub_events: "{{ stub_events + ['restart'] }}"
  tasks:
    - name: Serve the batch and keep a refusal
      block:
        - name: Serve the batch
          ansible.builtin.include_role:
            name: svc-stack
            tasks_from: batch/serve.yml
          vars:
            stack_batch_items: "{{ stub_plan }}"
      rescue:
        - name: Record the refusal
          ansible.builtin.set_fact:
            stub_refusal: "{{ ansible_failed_result.msg }}"

    - name: Report what the batch did
      ansible.builtin.copy:
        dest: "{{ report_out }}"
        content: >-
          {{ {'events': stub_events, 'refusal': stub_refusal | default(''),
              'record': front_proxy_batch_vhosts, 'served': stack_front_served,
              'running': stack_batch_running, 'deferred': stack_batch_deferred} | to_json }}
        mode: "0644"
"""


def _build(workdir: Path, *, guard: bool) -> None:
    """Args:
    workdir: an empty directory that becomes the playbook directory.
    guard: whether the role of ALPHA and LATE ships a stack guard.
    """
    if guard:
        _write(
            workdir / "roles" / ALPHA["role"] / "tasks/utils/stack/guard.yml",
            STUB_GUARD,
        )
    for path in REAL:
        _write(workdir / path, read_text(str(PROJECT_ROOT / path)))
    _write(workdir / STACK / "tasks/batch/front.yml", STUB_FRONT)
    bridge = read_text(str(PROJECT_ROOT / CANONICAL_BRIDGE))
    for item in (ALPHA, BETA, NESTED):
        _write(workdir / "roles" / item["role"] / "tasks/utils/stack.yml", bridge)
        _write(
            workdir / "roles" / item["role"] / ROLE_FILE_VARS_MAIN,
            f"---\nconsumer_scope: {item['role']}-vars\n",
        )
    for role, tasks in WARM:
        _write(workdir / "roles" / role / "tasks" / tasks, STUB_WARM)
    _write(workdir / "roles/sys-stk-front-base/tasks/once.yml", STUB_FRONT_BASE)
    _write(workdir / "lookup/stack_batch.py", STUB_LATE_LOOKUP)
    _write(
        workdir / "inventory.ini",
        "[svc-prx-openresty]\nlocalhost ansible_connection=local\n",
    )
    _write(
        workdir / "lookup/container_address.py",
        STUB_LOOKUP.replace("{RESULT}", "'openresty'"),
    )
    _write(workdir / "lookup/timeout.py", STUB_LOOKUP.replace("{RESULT}", "terms[0]"))
    _write(workdir / "library/uri_probe_batch.py", STUB_PROBE)
    _write(workdir / "bin/container", STUB_CONTAINER)
    (workdir / "bin/container").chmod(0o755)
    _write(workdir / "play.yml", PLAYBOOK)


def run_batch(
    plan: list[dict],
    *,
    probe: dict[str, int],
    test_rc: int = 0,
    test_stderr: str = "",
    reload_changed: bool = True,
    nest_late: bool = False,
    guard: bool = False,
    refuse_guard: bool = False,
) -> dict:
    """Args:
        plan: the front batch plan.
        probe: the status the stub probe answers per vhost.
        test_rc: the exit code of the stub ``openresty -t``.
        test_stderr: the error output of the stub ``openresty -t``.
        reload_changed: whether the stub reload reports a change.
        nest_late: whether the warm-up enters a bridged role outside the plan.
        guard: whether the role of ALPHA and LATE ships a stack guard.
        refuse_guard: whether that guard refuses the role.

    Returns:
        the batch events in order, the refusal message and the record left
        behind, plus the stub container calls.

    Raises:
        RuntimeError: when ansible-playbook exits non-zero.
    """
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        _build(workdir, guard=guard)
        report, calls = workdir / "report.json", workdir / "container.log"
        _write(
            workdir / "extra.json",
            json.dumps(
                {
                    "stub_plan": plan,
                    "IS_STACK_HOST": True,
                    "reload_changed": reload_changed,
                    "nest_late": nest_late,
                    "refuse_guard": refuse_guard,
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
            "STUB_CONTAINER_LOG": str(calls),
            "STUB_TEST_RC": str(test_rc),
            "STUB_TEST_STDERR": test_stderr,
            "STUB_PROBE_STATUS": json.dumps(probe),
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
        observed = json.loads(read_text(str(report)))
        observed["calls"] = read_text(str(calls)).splitlines() if calls.exists() else []
        return observed


def _warm(*roles: str) -> list[str]:
    return [f"warm:{role}" for role in roles]


def _front(item: dict) -> str:
    return f"front:{item['id']}|{item['id']}|front|{item['phase']}|{item['role']}-vars"


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
class TestFrontBatchRun(unittest.TestCase):
    def test_the_batch_warms_up_renders_reloads_once_and_restarts_once(self) -> None:
        observed = run_batch(
            [ALPHA, BETA],
            probe={"web-app-alpha.example": 404, "web-svc-beta.example": 200},
        )
        self.assertEqual(
            observed["events"],
            [
                *_warm(*(role for role, _ in WARM)),
                _front(ALPHA),
                _front(BETA),
                "reload",
                "restart",
            ],
        )
        self.assertEqual(observed["refusal"], "")
        self.assertEqual(observed["record"], {})
        self.assertEqual(observed["calls"], ["exec openresty openresty -t -q"])
        self.assertEqual(
            observed["served"], {"web-app-alpha": True, "web-svc-beta": True}
        )

    def test_each_guard_runs_in_its_role_scope_before_any_vhost_renders(
        self,
    ) -> None:
        observed = run_batch(
            [ALPHA, BETA],
            probe={"web-app-alpha.example": 200, "web-svc-beta.example": 200},
            guard=True,
        )
        self.assertEqual(
            observed["events"],
            [
                "guard:web-app-alpha|web-app-alpha|web-app-alpha-vars",
                *_warm(*(role for role, _ in WARM)),
                _front(ALPHA),
                _front(BETA),
                "reload",
            ],
        )

    def test_a_refusing_guard_stops_the_batch_before_the_warm_up(self) -> None:
        observed = run_batch([ALPHA, BETA], probe={}, guard=True, refuse_guard=True)
        self.assertEqual(observed["refusal"], "guard refused web-app-alpha")
        self.assertEqual(
            observed["events"],
            ["guard:web-app-alpha|web-app-alpha|web-app-alpha-vars"],
        )
        self.assertEqual((observed["served"], observed["calls"]), ({}, []))

    def test_a_late_item_runs_its_guard_before_its_warm_up(self) -> None:
        observed = run_batch([LATE], probe={"web-app-alpha.example": 200}, guard=True)
        self.assertEqual(
            observed["events"],
            [
                "guard:web-app-alpha|web-app-alpha|web-app-alpha-vars",
                *_warm(*(role for role, _ in WARM)),
                _front(LATE),
                "reload",
            ],
        )

    def test_a_late_item_renders_in_its_late_phase_with_its_warm_up(self) -> None:
        observed = run_batch([LATE], probe={"web-app-alpha.example": 200})
        self.assertEqual(
            observed["events"],
            [*_warm(*(role for role, _ in WARM)), _front(LATE), "reload"],
        )
        self.assertEqual(observed["served"], {"web-app-alpha": True})

    def test_a_late_front_entered_inside_the_batch_waits_for_its_end(self) -> None:
        observed = run_batch(
            [BETA],
            probe={"web-svc-beta.example": 200, "web-svc-nested.example": 200},
            nest_late=True,
        )
        self.assertEqual(
            observed["events"],
            [
                *_warm(
                    "sys-svc-webserver-https",
                    "sys-svc-container",
                    "sys-svc-webserver-core",
                    "sys-svc-nss",
                    "sys-stk-front-base",
                ),
                _front(BETA),
                "reload",
                _front(NESTED),
                "reload",
            ],
        )
        self.assertEqual(
            observed["served"], {"web-svc-beta": True, "web-svc-nested": True}
        )
        self.assertEqual((observed["running"], observed["deferred"]), (False, []))

    def test_a_plan_without_letsencrypt_skips_the_certificate_warm_up(self) -> None:
        observed = run_batch(
            [BETA], probe={"web-svc-beta.example": 503}, reload_changed=False
        )
        self.assertEqual(
            observed["events"],
            [
                *_warm(
                    "sys-svc-webserver-https",
                    "sys-svc-container",
                    "sys-svc-webserver-core",
                    "sys-svc-nss",
                    "sys-stk-front-base",
                ),
                _front(BETA),
                "reload",
                "restart",
            ],
        )

    def test_an_upstream_still_down_after_a_reload_restarts_nothing(self) -> None:
        observed = run_batch([BETA], probe={"web-svc-beta.example": 502})
        self.assertEqual(observed["events"][-2:], [_front(BETA), "reload"])

    def test_a_refused_config_names_its_role_and_keeps_the_live_config(self) -> None:
        observed = run_batch(
            [ALPHA, BETA],
            probe={},
            test_rc=1,
            test_stderr=(
                'nginx: [emerg] unknown directive "bogus" in '
                "/etc/nginx/conf.d/servers/https/web-app-alpha.example.conf:3"
            ),
        )
        self.assertIn(
            "OpenResty refuses the vhosts of web-app-alpha,", observed["refusal"]
        )
        self.assertNotIn("web-svc-beta,", observed["refusal"])
        self.assertNotIn("reload", observed["events"])
        self.assertEqual(
            sorted(observed["record"]),
            ["web-app-alpha.example", "web-svc-beta.example"],
        )

    def test_a_test_that_cites_no_vhost_leaves_the_judgement_to_the_reload(
        self,
    ) -> None:
        observed = run_batch(
            [BETA],
            probe={"web-svc-beta.example": 200},
            test_rc=1,
            test_stderr="Error response from daemon: container is restarting",
        )
        self.assertEqual(observed["refusal"], "")
        self.assertEqual(observed["events"][-1], "reload")


if __name__ == "__main__":
    unittest.main()
