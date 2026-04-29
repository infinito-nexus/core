"""Unit tests for roles/test-e2e-playwright/files/service-gating.js.

The helper is plain CommonJS. Its only external dependency is
`@playwright/test` for the `test.skip()` control flow. We fabricate a
tiny `node_modules/@playwright/test` stub in a temp dir so the helper
loads against a predictable fake, then call it from a short Node
script and assert the observable behaviour.
"""

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
HELPER_PATH = os.path.join(
    REPO_ROOT,
    "roles",
    "test-e2e-playwright",
    "files",
    "service-gating.js",
)

STUB_PKG_JSON = json.dumps({"name": "@playwright/test", "main": "index.js"})
STUB_INDEX_JS = textwrap.dedent(
    """
    const skipRecords = [];
    module.exports = {
      test: {
        skip(cond, reason) {
          if (cond) {
            skipRecords.push(reason || "");
            console.log("SKIP:" + (reason || ""));
            const e = new Error("skipped");
            e.__skipped = true;
            throw e;
          }
        },
      },
      expect: () => ({ toBeVisible: () => {}, toBeTruthy: () => {} }),
      __skipRecords: skipRecords,
    };
    """
)


def _have_node():
    return shutil.which("node") is not None


@unittest.skipUnless(_have_node(), "node is not available in PATH")
class TestServiceGatingHelper(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="sg-helper-")
        stub_dir = os.path.join(self.tmpdir, "node_modules", "@playwright", "test")
        os.makedirs(stub_dir, exist_ok=True)
        with open(os.path.join(stub_dir, "package.json"), "w") as f:
            f.write(STUB_PKG_JSON)
        with open(os.path.join(stub_dir, "index.js"), "w") as f:
            f.write(STUB_INDEX_JS)
        # Copy helper so `require("./service-gating")` works from the tmp dir.
        shutil.copy(HELPER_PATH, os.path.join(self.tmpdir, "service-gating.js"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run_in_node(self, snippet, env):
        script = textwrap.dedent(
            f"""
            const helper = require("./service-gating");
            (async () => {{
              try {{
                const result = await (async () => {{ {snippet} }})();
                process.stdout.write("RESULT:" + JSON.stringify(result ?? null) + "\\n");
              }} catch (err) {{
                if (err && err.__skipped) {{
                  process.exit(0);
                }}
                process.stdout.write(
                  "ERROR:" + (err && err.message ? err.message : String(err)) + "\\n"
                );
                process.exit(1);
              }}
            }})();
            """
        )
        script_path = os.path.join(self.tmpdir, "run.js")
        with open(script_path, "w") as f:
            f.write(script)
        proc = subprocess.run(
            ["node", "run.js"],
            capture_output=True,
            text=True,
            env={**os.environ, **env},
            cwd=self.tmpdir,
            timeout=10,
        )
        return proc

    # isServiceEnabled -----------------------------------------------------

    def test_enabled_when_flag_true(self):
        proc = self._run_in_node(
            "return helper.isServiceEnabled('oidc');",
            env={"OIDC_SERVICE_ENABLED": "true"},
        )
        self.assertEqual(
            proc.returncode, 0, msg=f"stderr={proc.stderr}\nstdout={proc.stdout}"
        )
        self.assertIn("RESULT:true", proc.stdout)

    def test_disabled_when_flag_false(self):
        proc = self._run_in_node(
            "return helper.isServiceEnabled('oidc');",
            env={
                "OIDC_SERVICE_ENABLED": "false",
                "EMAIL_SERVICE_ENABLED": "true",
            },
        )
        self.assertEqual(
            proc.returncode, 0, msg=f"stderr={proc.stderr}\nstdout={proc.stdout}"
        )
        self.assertIn("RESULT:false", proc.stdout)

    def test_strict_value_rejected(self):
        proc = self._run_in_node(
            "return helper.isServiceEnabled('oidc');",
            env={"OIDC_SERVICE_ENABLED": "yes"},
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("OIDC_SERVICE_ENABLED", proc.stdout)

    def test_unknown_service_hard_fails(self):
        # With a non-empty registry, an unknown service MUST throw.
        proc = self._run_in_node(
            "return helper.isServiceEnabled('oicd');",
            env={"OIDC_SERVICE_ENABLED": "true"},
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Unknown service", proc.stdout)

    def test_empty_registry_treats_everything_enabled(self):
        # No *_SERVICE_ENABLED in the env at all => legacy staged .env;
        # the helper MUST treat every service as enabled (backwards-compat).
        proc = self._run_in_node(
            "return helper.isServiceEnabled('oidc');",
            env={},
        )
        self.assertEqual(
            proc.returncode, 0, msg=f"stderr={proc.stderr}\nstdout={proc.stdout}"
        )
        self.assertIn("RESULT:true", proc.stdout)

    # isServiceDisabledReason ---------------------------------------------

    def test_disabled_reason_names_the_flag(self):
        proc = self._run_in_node(
            "return helper.isServiceDisabledReason('email');",
            env={
                "EMAIL_SERVICE_ENABLED": "false",
                "OIDC_SERVICE_ENABLED": "true",
            },
        )
        self.assertEqual(
            proc.returncode, 0, msg=f"stderr={proc.stderr}\nstdout={proc.stdout}"
        )
        self.assertIn("EMAIL_SERVICE_ENABLED=false", proc.stdout)

    def test_enabled_reason_is_null(self):
        proc = self._run_in_node(
            "return helper.isServiceDisabledReason('email');",
            env={"EMAIL_SERVICE_ENABLED": "true"},
        )
        self.assertEqual(
            proc.returncode, 0, msg=f"stderr={proc.stderr}\nstdout={proc.stdout}"
        )
        self.assertIn("RESULT:null", proc.stdout)

    # requireService -------------------------------------------------------

    def test_require_service_runs_testfn_when_enabled(self):
        proc = self._run_in_node(
            "const fn = helper.requireService('oidc', async () => 'HIT');"
            "return fn({});",
            env={"OIDC_SERVICE_ENABLED": "true"},
        )
        self.assertEqual(
            proc.returncode, 0, msg=f"stderr={proc.stderr}\nstdout={proc.stdout}"
        )
        self.assertIn('RESULT:"HIT"', proc.stdout)

    def test_require_service_skips_when_disabled(self):
        proc = self._run_in_node(
            "const fn = helper.requireService('oidc', async () => 'HIT');"
            "return fn({});",
            env={
                "OIDC_SERVICE_ENABLED": "false",
                "EMAIL_SERVICE_ENABLED": "true",
            },
        )
        self.assertEqual(
            proc.returncode, 0, msg=f"stderr={proc.stderr}\nstdout={proc.stdout}"
        )
        self.assertIn("SKIP:", proc.stdout)
        self.assertIn("OIDC_SERVICE_ENABLED=false", proc.stdout)


if __name__ == "__main__":
    unittest.main()
