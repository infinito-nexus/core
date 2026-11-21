from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_DEFAULTS_MAIN, ROLE_FILE_VARS_MAIN

from .test_stack_entry import _write

STACK = Path("roles/svc-stack")
REAL = (
    STACK / "tasks/deferred_probe.yml",
    STACK / "tasks/deferred_probe/restart.yml",
    STACK / ROLE_FILE_VARS_MAIN,
    STACK / ROLE_FILE_DEFAULTS_MAIN,
    STACK / "filter_plugins/front_proxy_unserved.py",
)
QUEUE = {
    domain: {"url": f"https://{domain}/", "status_codes": [200], "phase": phase}
    for domain, phase in (
        ("self.example", "entered"),
        ("shared.example", "preload"),
        ("app.example", "server"),
    )
}

STUB_TIMEOUT = """from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        return [terms[0]]
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
    with open(os.environ["STUB_PROBE_LOG"], "a", encoding="utf-8") as log:
        log.write(json.dumps(sorted(module.params["urls"])) + "\\n")
    module.exit_json(changed=False, status=dict.fromkeys(module.params["urls"], 200))


main()
"""

PLAYBOOK = """---
- name: Probe a queue that mixes the stack phases
  hosts: svc-prx-openresty
  gather_facts: false
  handlers:
    - name: Record the restart
      listen: restart-openresty
      ansible.builtin.debug:
        msg: restart
  tasks:
    - name: Queue one vhost per phase
      ansible.builtin.set_fact:
        front_proxy_deferred_probes: "{{ queue }}"

    - name: Probe after the loader
      ansible.builtin.include_role:
        name: svc-stack
        tasks_from: deferred_probe.yml
      vars:
        front_proxy_probe_phases: [entered, preload]

    - name: Keep the queue the loader left
      ansible.builtin.set_fact:
        queue_after_loader: "{{ front_proxy_deferred_probes.keys() | list | sort }}"

    - name: Probe after the server roles
      ansible.builtin.include_role:
        name: svc-stack
        tasks_from: deferred_probe.yml
      vars:
        front_proxy_probe_phases: [entered, preload, server]

    - name: Report the queues
      ansible.builtin.copy:
        dest: "{{ report_out }}"
        content: >-
          {{ {'after_loader': queue_after_loader,
              'after_server': front_proxy_deferred_probes.keys() | list} | to_json }}
        mode: "0644"
"""


def run_phases() -> dict:
    """Returns:
        the queue left after each probe point and the vhosts each probe sent.

    Raises:
        RuntimeError: when ansible-playbook exits non-zero.
    """
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        for path in REAL:
            _write(workdir / path, read_text(str(PROJECT_ROOT / path)))
        _write(workdir / "lookup/timeout.py", STUB_TIMEOUT)
        _write(workdir / "library/uri_probe_batch.py", STUB_PROBE)
        _write(
            workdir / "inventory.ini",
            "[svc-prx-openresty]\nlocalhost ansible_connection=local\n",
        )
        _write(workdir / "play.yml", PLAYBOOK)
        report, probes = workdir / "report.json", workdir / "probes.log"
        _write(
            workdir / "extra.json",
            json.dumps({"queue": QUEUE, "report_out": str(report)}),
        )
        env = {
            **os.environ,
            "ANSIBLE_ROLES_PATH": str(workdir / "roles"),
            "ANSIBLE_LOOKUP_PLUGINS": str(workdir / "lookup"),
            "ANSIBLE_LIBRARY": str(workdir / "library"),
            "STUB_PROBE_LOG": str(probes),
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
        observed["probes"] = [
            json.loads(line) for line in read_text(str(probes)).splitlines()
        ]
        return observed


def stage_probe_phases(stage: str) -> list[str]:
    """Args:
        stage: the stage file under tasks/stages.

    Returns:
        the front_proxy_probe_phases the stage passes to its deferred probe.
    """
    tasks = load_yaml_any(str(PROJECT_ROOT / "tasks/stages" / stage)) or []
    probe = next(
        task
        for task in tasks
        if (task.get("ansible.builtin.include_role") or {}).get("tasks_from")
        == "deferred_probe.yml"
    )
    return probe["vars"]["front_proxy_probe_phases"]


class TestTheStagesProbeTheirPhases(unittest.TestCase):
    def test_the_loader_probe_takes_the_vhosts_that_have_a_backend(self) -> None:
        self.assertEqual(
            stage_probe_phases("01_constructor.yml"), ["entered", "preload"]
        )

    def test_the_server_probe_takes_every_phase(self) -> None:
        self.assertEqual(
            stage_probe_phases("02_server.yml"),
            ["entered", "preload", "server", "late"],
        )


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
class TestDeferredProbePhases(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.observed = run_phases()

    def test_the_loader_probe_skips_the_vhosts_of_server_roles(self) -> None:
        self.assertEqual(self.observed["probes"][0], ["self.example", "shared.example"])
        self.assertEqual(self.observed["after_loader"], ["app.example"])

    def test_the_server_probe_takes_the_rest_and_empties_the_queue(self) -> None:
        self.assertEqual(self.observed["probes"][1], ["app.example"])
        self.assertEqual(self.observed["after_server"], [])


if __name__ == "__main__":
    unittest.main()
