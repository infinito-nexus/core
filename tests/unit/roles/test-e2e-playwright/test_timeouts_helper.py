"""Unit tests for roles/test-e2e-playwright/files/timeouts.js.

The helper is dependency-free plain CommonJS. We copy it into a temp dir
and call it from a short Node script with controlled env, then assert the
computed timeout / onion detection.
"""

import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from . import PROJECT_ROOT

HELPER_PATH = str(
    PROJECT_ROOT / "roles" / "test-e2e-playwright" / "files" / "timeouts.js"
)


def _have_node():
    return shutil.which("node") is not None


@unittest.skipUnless(_have_node(), "node is not available in PATH")
class TestTimeoutsHelper(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="timeouts-helper-")
        shutil.copy(HELPER_PATH, str(Path(self.tmpdir) / "timeouts.js"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run(self, expr, env):
        script = textwrap.dedent(
            f"""
            const t = require("./timeouts");
            process.stdout.write("RESULT:" + JSON.stringify({expr}) + "\\n");
            """
        )
        script_path = str(Path(self.tmpdir) / "run.js")
        with Path(script_path).open("w") as f:
            f.write(script)
        proc = subprocess.run(
            ["node", "run.js"],
            capture_output=True,
            text=True,
            env={**os.environ, **env},
            cwd=self.tmpdir,
            timeout=10,
            check=False,
        )
        self.assertEqual(
            proc.returncode, 0, msg=f"stderr={proc.stderr}\nstdout={proc.stdout}"
        )
        return proc.stdout

    def test_clearnet_default_factor_is_identity(self):
        out = self._run(
            "t.resolveTimeout(60000)",
            {"CANONICAL_DOMAIN": '"x.infinito.example"'},
        )
        self.assertIn("RESULT:60000", out)

    def test_onion_applies_default_multiplier(self):
        out = self._run(
            "t.resolveTimeout(60000)",
            {"CANONICAL_DOMAIN": '"x.abc123.onion"'},
        )
        self.assertIn("RESULT:300000", out)

    def test_global_factor_scales_clearnet(self):
        out = self._run(
            "t.resolveTimeout(60000)",
            {"CANONICAL_DOMAIN": "x.infinito.example", "PLAYWRIGHT_TIMEOUT_FACTOR": "2"},
        )
        self.assertIn("RESULT:120000", out)

    def test_factor_and_onion_multiplier_compose(self):
        out = self._run(
            "t.resolveTimeout(60000)",
            {
                "CANONICAL_DOMAIN": '"x.abc123.onion"',
                "PLAYWRIGHT_TIMEOUT_FACTOR": "2",
                "PLAYWRIGHT_ONION_TIMEOUT_MULTIPLIER": "3",
            },
        )
        self.assertIn("RESULT:360000", out)

    def test_invalid_factor_falls_back_to_one(self):
        out = self._run(
            "t.resolveTimeout(60000)",
            {"CANONICAL_DOMAIN": "x.infinito.example", "PLAYWRIGHT_TIMEOUT_FACTOR": "0"},
        )
        self.assertIn("RESULT:60000", out)

    def test_is_onion_target_detects_quoted_and_bare(self):
        self.assertIn("RESULT:true", self._run("t.isOnionTarget()", {"CANONICAL_DOMAIN": '"x.abc.onion"'}))
        self.assertIn("RESULT:true", self._run("t.isOnionTarget()", {"CANONICAL_DOMAIN": "x.abc.onion"}))
        self.assertIn("RESULT:false", self._run("t.isOnionTarget()", {"CANONICAL_DOMAIN": '"x.infinito.example"'}))


if __name__ == "__main__":
    unittest.main()
