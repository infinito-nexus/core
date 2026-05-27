import os
import subprocess
import unittest

from . import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "scripts" / "meta" / "resolve" / "pr" / "branch_prefix.sh"


class TestPullRequestBranchPrefix(unittest.TestCase):
    def _run_script(self, *, scope: str, head_ref: str):
        env = os.environ.copy()
        env.update(
            {
                "PR_SCOPE": scope,
                "PR_HEAD_REF": head_ref,
            }
        )

        return subprocess.run(
            ["bash", str(SCRIPT_PATH)],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_agents_scope_accepts_agent_prefix(self):
        result = self._run_script(scope="agents", head_ref="agent/debugging-guidance")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Validated branch prefix 'agent'", result.stdout)

    def test_documentation_scope_accepts_documentation_prefix(self):
        result = self._run_script(
            scope="documentation", head_ref="documentation/docker-guide"
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Validated branch prefix 'documentation'", result.stdout)

    def test_full_scope_accepts_feature_prefix(self):
        result = self._run_script(scope="full", head_ref="feature/add-matomo")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Validated branch prefix 'feature'", result.stdout)

    def test_full_scope_accepts_fix_prefix(self):
        result = self._run_script(scope="full", head_ref="fix/login-redirect")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Validated branch prefix 'fix'", result.stdout)

    def test_full_scope_accepts_chore_prefix(self):
        result = self._run_script(
            scope="full", head_ref="chore/update-docker-image-versions"
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Validated branch prefix 'chore'", result.stdout)

    def test_mismatched_prefix_fails(self):
        result = self._run_script(scope="documentation", head_ref="feature/add-docs")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "does not match scope 'documentation'",
            result.stderr,
        )


if __name__ == "__main__":
    unittest.main()
