"""Contract of ``make agents-verify`` (``scripts/agents/verify.sh``).

Without ``scenario`` it hands ``call-test-agents-local.yml`` to act, the file
the CI runs, after refusing a swarm run off a worktree slot in 3..10; with
``scenario`` it replays that one scenario against the running stack and
neither starts act nor checks the slot. The env loader, the interpreter and
act are stubs, so nothing here deploys.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

VERIFY = PROJECT_ROOT / "scripts" / "agents" / "verify.sh"
STUBS = {
    "scripts/meta/env/load.sh": (
        'PYTHON="$(dirname "${BASH_SOURCE[0]}")/python-stub"\n'
    ),
    "scripts/meta/env/python-stub": "#!/usr/bin/env bash\nprintf 'python %s\\n' \"$*\"\n",
    "scripts/tests/deploy/act/workflow.sh": (
        'printf \'act %s matrix=%s\\n\' "${ACT_WORKFLOW}" "${ACT_MATRIX}"\n'
    ),
}
LOCAL = "act .github/workflows/call-test-agents-local.yml"


class TestVerify(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        script = self.root / "scripts" / "agents" / "verify.sh"
        script.parent.mkdir(parents=True)
        shutil.copy2(VERIFY, script)
        for rel, text in STUBS.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            path.chmod(0o755)
        self.script = script

    def _run(self, *, slot: str, mode: str = "", scenario: str = ""):
        env = {
            k: v
            for k, v in os.environ.items()
            if k != "BASH_ENV" and not k.startswith("INFINITO_")
        }
        env.update(INFINITO_INSTANCE=slot, mode=mode, scenario=scenario)
        return subprocess.run(
            ["bash", str(self.script)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_swarm_above_slot_ten_is_refused_and_names_the_fix(self):
        for mode in ("swarm", ""):
            with self.subTest(mode=mode):
                done = self._run(slot="11", mode=mode)
                self.assertEqual(done.returncode, 2, done.stdout)
                self.assertIn("slot 11", done.stderr)
                self.assertIn("Fix:", done.stderr)
                self.assertNotIn("act ", done.stdout)

    def test_swarm_below_slot_three_or_no_number_is_refused(self):
        for slot in ("0", "x"):
            with self.subTest(slot=slot):
                self.assertEqual(self._run(slot=slot, mode="swarm").returncode, 2)

    def test_a_slot_in_range_runs_the_ci_workflow_through_act(self):
        self.assertEqual(
            self._run(slot="10", mode="swarm").stdout, f"{LOCAL} matrix=mode:swarm\n"
        )
        self.assertEqual(self._run(slot="3").stdout, f"{LOCAL} matrix=\n")

    def test_compose_needs_no_swarm_slot(self):
        done = self._run(slot="11", mode="compose")
        self.assertEqual(done.stdout, f"{LOCAL} matrix=mode:compose\n")

    def test_one_scenario_replays_without_act_or_slot_check(self):
        done = self._run(slot="42", scenario="hacker-bruteforce")
        self.assertEqual(
            done.stdout, "python -m cli.agents.scenarios --scenario hacker-bruteforce\n"
        )

    def test_an_unknown_mode_is_refused(self):
        self.assertEqual(self._run(slot="5", mode="k8s").returncode, 2)


if __name__ == "__main__":
    unittest.main()
