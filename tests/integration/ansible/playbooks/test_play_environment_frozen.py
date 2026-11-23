"""The play environment is rendered once per host and checked against its sources.

``playbook.yml`` passes its environment as the ``PLAY_ENVIRONMENT`` mapping
that ``tasks/utils/play/environment/freeze.yml`` renders once, so no task
compiles the source templates again. ``environment/check.yml`` runs at the
end of the play and fails when a source changed after the freeze, because
every task after the change ran with the stale value.

These cases run real Ansible with the two shared task files: the frozen value
reaches a task, a handler and a delegated task while a task's own
``environment:`` still wins, a source changed mid-play fails the check, and a
``--tags`` run still freezes and checks.
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import read_text

from . import PROJECT_ROOT

FREEZE = PROJECT_ROOT / "tasks/utils/play/environment/freeze.yml"
CHECK = PROJECT_ROOT / "tasks/utils/play/environment/check.yml"
PLAYBOOK = PROJECT_ROOT / "playbook.yml"

PLAY = f"""---
- name: Freeze the play environment and check it at the end
  hosts: localhost
  gather_facts: false
  vars:
    probe_source: frozen
    PLAY_ENVIRONMENT_SOURCE:
      PROBE_VALUE: "{{{{ probe_source }}}}"
    PLAY_ENVIRONMENT: "{{{{ PLAY_ENVIRONMENT_SOURCE }}}}"
  environment: "{{{{ PLAY_ENVIRONMENT }}}}"
  pre_tasks:
    - name: Freeze
      ansible.builtin.include_tasks:
        file: {FREEZE}
        apply:
          tags: [always]
      tags: [always]
  tasks:
    - name: Report the value a module sees
      ansible.builtin.shell: printf '%s' "$PROBE_VALUE" > "{{{{ probe_dir }}}}/task"
      changed_when: true
      notify: Report the value a handler sees
      tags: [probe]

    - name: Report the value a task with its own environment sees
      ansible.builtin.shell: printf '%s' "$PROBE_VALUE" > "{{{{ probe_dir }}}}/override"
      environment:
        PROBE_VALUE: own
      changed_when: false
      tags: [probe]

    - name: Report the value a delegated task sees
      ansible.builtin.shell: printf '%s' "$PROBE_VALUE" > "{{{{ probe_dir }}}}/delegated"
      delegate_to: localhost
      changed_when: false
      tags: [probe]

    - name: Change the source mid-play
      ansible.builtin.set_fact:
        probe_source: changed
      when: change_source | bool
      tags: [probe]
  handlers:
    - name: Report the value a handler sees
      ansible.builtin.shell: printf '%s' "$PROBE_VALUE" > "{{{{ probe_dir }}}}/handler"
      changed_when: false
  post_tasks:
    - name: Check
      ansible.builtin.include_tasks:
        file: {CHECK}
        apply:
          tags: [always]
      tags: [always]
"""

PROBES = ("task", "override", "delegated", "handler")


def _run(change_source: bool, tags: list[str]) -> tuple[int, str, dict[str, str]]:
    """Run the play once.

    Args:
        change_source: whether the play changes the source after the freeze.
        tags: the ``--tags`` to pass, none for a full run.

    Returns:
        ``(exit code, combined output, value each probe saw)``.
    """
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        (workdir / "play.yml").write_text(PLAY, encoding="utf-8")
        result = subprocess.run(
            [
                "ansible-playbook",
                "-i",
                "localhost,",
                "-c",
                "local",
                str(workdir / "play.yml"),
                "-e",
                f"probe_dir={workdir}",
                "-e",
                f"change_source={change_source}",
                *[f"--tags={tag}" for tag in tags],
            ],
            cwd=str(workdir),
            capture_output=True,
            text=True,
            check=False,
        )
        seen = {
            probe: read_text(str(workdir / probe))
            for probe in PROBES
            if (workdir / probe).exists()
        }
    return result.returncode, result.stdout + result.stderr, seen


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
class TestPlayEnvironmentFrozen(unittest.TestCase):
    def test_tasks_handlers_and_delegates_see_the_frozen_value(self):
        code, output, seen = _run(change_source=False, tags=[])
        self.assertEqual(code, 0, output)
        self.assertEqual(
            seen,
            {
                "task": "frozen",
                "override": "own",
                "delegated": "frozen",
                "handler": "frozen",
            },
        )

    def test_a_source_changed_mid_play_fails_the_check(self):
        code, output, seen = _run(change_source=True, tags=[])
        self.assertNotEqual(code, 0, output)
        self.assertEqual(seen["task"], "frozen")
        self.assertIn("A source of the play environment changed", output)

    def test_a_tagged_run_still_freezes_and_checks(self):
        code, output, seen = _run(change_source=True, tags=["probe"])
        self.assertNotEqual(code, 0, output)
        self.assertEqual(seen["task"], "frozen")
        self.assertIn("A source of the play environment changed", output)


class TestPlaybookUsesTheFrozenEnvironment(unittest.TestCase):
    def test_the_playbook_freezes_first_and_checks_last(self):
        text = read_text(str(PLAYBOOK))
        self.assertIn('environment: "{{ PLAY_ENVIRONMENT }}"', text)
        self.assertIn('PLAY_ENVIRONMENT: "{{ PLAY_ENVIRONMENT_SOURCE }}"', text)
        pre_tasks = text.index("pre_tasks:")
        self.assertLess(
            pre_tasks, text.index("tasks/utils/play/environment/freeze.yml")
        )
        self.assertLess(
            text.index("tasks/utils/play/environment/freeze.yml"),
            text.index("ansible.builtin.script: scripts/system/python"),
        )
        self.assertLess(
            text.index("post_tasks:"),
            text.index("tasks/utils/play/environment/check.yml"),
        )


if __name__ == "__main__":
    unittest.main()
