import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from . import PROJECT_ROOT

REAL_ROLES = ("web-app-nextcloud", "web-app-matomo")


class TestSubsetRoles(unittest.TestCase):
    """Exercises the cli.meta.ci.subset_roles resolver behind the '🧩 Subset'
    label.

    The "no subset label" case (existing diff behaviour stays unchanged) is
    covered by test_diff_affected_roles.py: this module only ever runs when
    the label gates it in entry-pull-request-change.yml.
    """

    def _run(self, body: str):
        with tempfile.TemporaryDirectory() as tmp:
            output_file = Path(tmp) / "output.txt"
            output_file.touch()

            env = os.environ.copy()
            env["PR_BODY"] = body
            env["GITHUB_OUTPUT"] = str(output_file)

            result = subprocess.run(
                ["python", "-m", "cli.meta.ci.subset_roles"],
                cwd=PROJECT_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            outputs = {}
            raw = output_file.read_text(encoding="utf-8")  # nocheck: cache-read
            for line in raw.splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    outputs[key] = value
            return result, outputs

    def test_valid_roles_produce_whitelist(self):
        body = (
            "## Roles\n\n```yaml\nroles:\n"
            f"  - {REAL_ROLES[0]}\n  - {REAL_ROLES[1]}\n```\n"
        )
        result, outputs = self._run(body)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs["whitelist"], " ".join(REAL_ROLES))
        self.assertEqual(outputs["roles_only"], "true")

    def test_invalid_yaml_fails(self):
        body = "```yaml\nroles:\n  - web-app-nextcloud\n   bad: : :\n```\n"
        result, outputs = self._run(body)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid YAML", result.stderr)
        self.assertNotIn("whitelist", outputs)

    def test_unknown_role_fails(self):
        body = "```yaml\nroles:\n  - web-app-nextcloud\n  - web-app-ghost-xyz\n```\n"
        result, outputs = self._run(body)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("web-app-ghost-xyz", result.stderr)
        self.assertNotIn("whitelist", outputs)

    def test_path_traversal_id_is_rejected(self):
        body = "```yaml\nroles:\n  - ../../etc\n```\n"
        result, outputs = self._run(body)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid role id", result.stderr)
        self.assertNotIn("whitelist", outputs)

    def test_empty_role_list_fails(self):
        body = "```yaml\nroles:\n```\n"
        result, _ = self._run(body)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("empty", result.stderr)

    def test_missing_block_fails(self):
        result, _ = self._run("No machine-readable roles block here.\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no fenced", result.stderr)


if __name__ == "__main__":
    unittest.main()
