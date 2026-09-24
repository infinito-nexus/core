"""A role must see its own application_id even after a foreign role's vars load.

``include_vars`` without ``name:`` puts every key of the loaded file into play
scope as a host fact, and a host fact outranks the role vars a role declares for
itself. The E2E stages load each tested role's ``vars/main.yml`` that way to
render that role's own templates, so the last tested role's ``application_id``
outlives the loop and every role set up afterwards resolves
``lookup('config', application_id, ...)`` under the wrong id.

``tasks/utils/setup/role.yml`` defeats that by passing ``application_id`` as an
include param, which outranks the fact. These cases run real Ansible: the first
reproduces the shadowing so the second cannot pass vacuously.
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_all_str
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

INCLUDE_SITE = PROJECT_ROOT / "tasks/utils/setup/role.yml"
FOREIGN_ID = "web-svc-mirror"
OWN_ID = "dsk-gnt-claude"

PROBE_TASK = """---
- name: Report the application_id the role sees
  ansible.builtin.copy:
    dest: "{{ probe_out }}"
    content: "{{ application_id }}"
    mode: "0644"
"""

PLAYBOOK = """---
- name: Prove an include param survives a foreign vars load
  hosts: localhost
  gather_facts: false
  connection: local
  tasks:
    - name: Leak a foreign application_id the way the E2E stages do
      ansible.builtin.include_vars:
        file: "{{ poison_file }}"

    - name: Without the include param the role sees the foreign id
      ansible.builtin.include_role:
        name: probe
      vars:
        probe_out: "{{ shadowed_out }}"

    - name: With the include param the role sees its own id
      ansible.builtin.include_role:
        name: probe
      vars:
        probe_out: "{{ bound_out }}"
        application_id: "{{ own_id }}"
"""


def _run_play(workdir: Path) -> tuple[str, str]:
    """Render the fixture tree, run the play once, return both observed ids.

    Args:
        workdir: an empty directory to build the role and the play in.

    Returns:
        ``(shadowed, bound)``: what the role saw without and with the param.

    Raises:
        RuntimeError: when ansible-playbook exits non-zero.
    """
    role = workdir / "roles" / "probe"
    for relative, body in (
        (ROLE_FILE_TASKS_MAIN, PROBE_TASK),
        (ROLE_FILE_VARS_MAIN, "---\napplication_id: probe\n"),
    ):
        target = role / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
    (workdir / "poison.yml").write_text(f"---\napplication_id: {FOREIGN_ID}\n")
    (workdir / "play.yml").write_text(PLAYBOOK)

    shadowed = workdir / "shadowed.txt"
    bound = workdir / "bound.txt"
    result = subprocess.run(
        [
            "ansible-playbook",
            "-i",
            "localhost,",
            "-c",
            "local",
            str(workdir / "play.yml"),
            "-e",
            f"poison_file={workdir / 'poison.yml'}",
            "-e",
            f"shadowed_out={shadowed}",
            "-e",
            f"bound_out={bound}",
            "-e",
            f"own_id={OWN_ID}",
        ],
        cwd=str(workdir),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ansible-playbook failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return read_text(str(shadowed)), read_text(str(bound))


class TestApplicationIdSurvivesAForeignLoad(unittest.TestCase):
    observed: ClassVar[dict[str, str]] = {}

    @classmethod
    def setUpClass(cls) -> None:
        """One play answers both cases, so it runs once rather than per case."""
        if not shutil.which("ansible-playbook"):
            return
        with tempfile.TemporaryDirectory() as tmp:
            shadowed, bound = _run_play(Path(tmp))
        cls.observed = {"shadowed": shadowed, "bound": bound}

    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
    def test_a_foreign_load_shadows_a_role_that_takes_no_param(self) -> None:
        self.assertEqual(
            self.observed["shadowed"],
            FOREIGN_ID,
            "the hazard this guards against must be reproducible, or the case "
            "below passes without proving anything",
        )

    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
    def test_the_include_param_outranks_the_leaked_fact(self) -> None:
        self.assertEqual(self.observed["bound"], OWN_ID)

    def test_the_shared_include_site_binds_the_application_id(self) -> None:
        tasks = [
            task
            for doc in load_yaml_all_str(read_text(str(INCLUDE_SITE)))
            if doc
            for task in doc
            if isinstance(task, dict) and "ansible.builtin.include_role" in task
        ]
        self.assertTrue(tasks, f"no include_role task in {INCLUDE_SITE}")
        for task in tasks:
            self.assertEqual(
                (task.get("vars") or {}).get("application_id"),
                "{{ role_entry.app }}",
                f"{INCLUDE_SITE} must bind application_id, or every role set up "
                f"after an E2E stage resolves its config under a foreign id",
            )


if __name__ == "__main__":
    unittest.main()
