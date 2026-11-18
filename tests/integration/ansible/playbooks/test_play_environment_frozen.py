"""The play environment is rendered once per host and checked against its sources.

``playbook.yml`` passes its environment as the ``PLAY_ENVIRONMENT`` mapping
that ``tasks/utils/play/environment/freeze.yml`` renders once, so no task
compiles the source templates again. ``environment/check.yml`` runs at the
end of the play and fails when a source changed after the freeze, because
every task after the change ran with the stale value.

These cases run real Ansible with the two shared task files: the frozen value
reaches a module's environment, and a source changed mid-play fails the check.
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
      ansible.builtin.include_tasks: {FREEZE}
  tasks:
    - name: Report the value a module sees
      ansible.builtin.shell: printf '%s' "$PROBE_VALUE" > "{{{{ probe_out }}}}"
      changed_when: false

    - name: Change the source mid-play
      ansible.builtin.set_fact:
        probe_source: changed
      when: change_source | bool
  post_tasks:
    - name: Check
      ansible.builtin.include_tasks: {CHECK}
"""


def _run(change_source: bool) -> tuple[int, str, str]:
    """Run the play once.

    Args:
        change_source: whether the play changes the source after the freeze.

    Returns:
        ``(exit code, combined output, value the module saw)``.
    """
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        (workdir / "play.yml").write_text(PLAY, encoding="utf-8")
        probe_out = workdir / "probe.txt"
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
                "-e",
                f"change_source={change_source}",
            ],
            cwd=str(workdir),
            capture_output=True,
            text=True,
            check=False,
        )
        seen = read_text(str(probe_out)) if probe_out.exists() else ""
    return result.returncode, result.stdout + result.stderr, seen


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
class TestPlayEnvironmentFrozen(unittest.TestCase):
    def test_a_module_sees_the_frozen_value_and_the_check_passes(self):
        code, output, seen = _run(change_source=False)
        self.assertEqual(code, 0, output)
        self.assertEqual(seen, "frozen")

    def test_a_source_changed_mid_play_fails_the_check(self):
        code, output, seen = _run(change_source=True)
        self.assertNotEqual(code, 0, output)
        self.assertEqual(seen, "frozen")
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
