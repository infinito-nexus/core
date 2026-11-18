"""The applications carrier must reach every later worker without the fact cache.

``get_vars`` deep-copies every fact before every task, twice while facts are
injected as top-level variables, so a carrier parked as a fact makes every
task pay for the whole rendered applications tree. With fact injection off,
a carrier parked as a fact also disappears from the top-level variables the
readers consult, and every lookup renders the payload again.

These cases run real Ansible with fake ``applications`` and ``users`` lookups
in front of the real ``applications_carrier`` action: the carrier must be
visible to a later task's worker with injection on and off and never sit in
``ansible_facts``. The hazard case parks a carrier the old way, as a fact, so
the reader guard is shown to turn the invisible carrier into a failed task.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.carrier import (
    APPLICATIONS_RENDERED_FACT,
    USERS_RENDERED_FACT,
)
from utils.cache.files import read_text

from . import PROJECT_ROOT

APPLICATIONS_KEY = ["roles", ["signature"]]
USERS_KEY = ["roles", ["signature", "localhost"]]

FAKE_APPLICATIONS = f"""
from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        return [{{"key": {APPLICATIONS_KEY!r}, "applications": {{"web-app-x": {{}}}}}}]
"""

FAKE_USERS = f"""
from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        return [{{"key": {USERS_KEY!r}, "users": {{"alice": {{}}}}}}]
"""

PROBE = f"""
from ansible.plugins.lookup import LookupBase

from utils.cache.carrier import _carried_applications, _carried_users


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        variables = variables or {{}}
        facts = variables.get("ansible_facts") or {{}}
        return [{{
            "applications": _carried_applications(
                variables, ({APPLICATIONS_KEY[0]!r}, tuple({APPLICATIONS_KEY[1]!r}))
            ) is not None,
            "users": _carried_users(
                variables, ({USERS_KEY[0]!r}, tuple({USERS_KEY[1]!r}))
            ) is not None,
            "fact_cache": sorted(
                name for name in ({APPLICATIONS_RENDERED_FACT!r}, {USERS_RENDERED_FACT!r})
                if name in facts
            ),
        }}]
"""

FACT_CARRIER = f"""
from ansible.plugins.action import ActionBase


class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        result = super().run(tmp, task_vars)
        result.update(
            changed=False,
            ansible_facts={{
                {APPLICATIONS_RENDERED_FACT!r}: {{
                    "key": {APPLICATIONS_KEY!r},
                    "applications": {{"web-app-x": {{}}}},
                }}
            }},
        )
        return result
"""

CARRIER_PLAY = """---
- name: Park the carrier and read it from later workers
  hosts: localhost
  gather_facts: false
  tasks:
    - name: Park the carrier
      applications_carrier: {}

    - name: Read the parked carrier in a later worker
      ansible.builtin.set_fact:
        probe_parked: "{{ lookup('carrier_probe') }}"

    - name: Drop the carrier
      applications_carrier:
        clear: true

    - name: Read after the drop
      ansible.builtin.set_fact:
        probe_cleared: "{{ lookup('carrier_probe') }}"

    - name: Report both reads
      ansible.builtin.copy:
        dest: "{{ probe_out }}"
        content: "{{ {'parked': probe_parked, 'cleared': probe_cleared} | to_json }}"
        mode: "0644"
"""

HAZARD_PLAY = """---
- name: Park the carrier as a fact and read it
  hosts: localhost
  gather_facts: false
  tasks:
    - name: Park the carrier in the fact cache
      fact_carrier: {}

    - name: Read the fact-parked carrier
      ansible.builtin.copy:
        dest: "{{ probe_out }}"
        content: "{{ lookup('carrier_probe') | to_json }}"
        mode: "0644"
"""


def _run(workdir: Path, play: str, inject: bool) -> tuple[int, str, dict | None]:
    """Run *play* once with fact injection set to *inject*.

    Args:
        workdir: an empty directory to build the plugins and the play in.
        play: the playbook text.
        inject: the value of ``ANSIBLE_INJECT_FACT_VARS``.

    Returns:
        ``(exit code, combined output, probe report or None)``.
    """
    lookups = workdir / "lookup"
    actions = workdir / "action"
    for directory, name, body in (
        (lookups, "applications.py", FAKE_APPLICATIONS),
        (lookups, "users.py", FAKE_USERS),
        (lookups, "carrier_probe.py", PROBE),
        (actions, "fact_carrier.py", FACT_CARRIER),
    ):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).write_text(body, encoding="utf-8")
    (workdir / "play.yml").write_text(play, encoding="utf-8")
    probe_out = workdir / "probe.json"

    env = os.environ.copy()
    env.update(
        ANSIBLE_CONFIG=str(PROJECT_ROOT / "ansible.cfg"),
        ANSIBLE_LOCAL_TEMP=str(workdir / "ansible-local"),
        ANSIBLE_LOOKUP_PLUGINS=str(lookups),
        ANSIBLE_ACTION_PLUGINS=f"{actions}:{PROJECT_ROOT / 'plugins/action'}",
        ANSIBLE_INJECT_FACT_VARS=str(inject),
        PYTHONPATH=os.pathsep.join(
            part for part in (str(PROJECT_ROOT), env.get("PYTHONPATH")) if part
        ),
    )
    result = subprocess.run(
        [
            "ansible-playbook",
            "-i",
            "localhost,",
            "-c",
            "local",
            str(workdir / "play.yml"),
            "-e",
            f"probe_out={probe_out}",
        ],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    report = json.loads(read_text(str(probe_out))) if probe_out.exists() else None
    return result.returncode, result.stdout + result.stderr, report


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
class TestApplicationsCarrierReachesLaterWorkers(unittest.TestCase):
    def _play(self, play: str, inject: bool) -> tuple[int, str, dict | None]:
        with tempfile.TemporaryDirectory() as tmp:
            return _run(Path(tmp), play, inject)

    def test_the_carrier_reaches_later_workers_outside_the_fact_cache(self):
        for inject in (True, False):
            with self.subTest(inject=inject):
                code, output, report = self._play(CARRIER_PLAY, inject)
                self.assertEqual(code, 0, output)
                self.assertNotIn("template error", output)
                self.assertEqual(
                    report["parked"],
                    {"applications": True, "users": True, "fact_cache": []},
                )
                self.assertEqual(
                    report["cleared"],
                    {"applications": False, "users": False, "fact_cache": []},
                )

    def test_a_fact_parked_carrier_is_visible_only_while_facts_are_injected(self):
        code, output, report = self._play(HAZARD_PLAY, True)
        self.assertEqual(code, 0, output)
        self.assertEqual(
            report,
            {
                "applications": True,
                "users": False,
                "fact_cache": [APPLICATIONS_RENDERED_FACT],
            },
            "the hazard must be reproducible with injection on, or the case "
            "below proves nothing",
        )

    def test_the_reader_fails_on_a_fact_parked_carrier_without_injection(self):
        code, output, report = self._play(HAZARD_PLAY, False)
        self.assertNotEqual(code, 0, output)
        self.assertIsNone(report)
        self.assertIn("not visible as a variable", output)


if __name__ == "__main__":
    unittest.main()
