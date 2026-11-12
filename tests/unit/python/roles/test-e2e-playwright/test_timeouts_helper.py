import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from plugins.lookup.network_suffixes import LookupModule as NetworkSuffixes
from utils.domains.default_primary import default_domain_primary

from . import PROJECT_ROOT

HELPER_PATH = str(
    PROJECT_ROOT / "roles" / "test-e2e-playwright" / "files" / "timeouts.js"
)
NETWORK_PATH = (
    PROJECT_ROOT / "roles/test-e2e-playwright/files/personas/utils/network.js"
)
SUFFIXES = json.dumps(NetworkSuffixes().run([])[0])
DOMAIN = default_domain_primary()


def _have_node():
    return shutil.which("node") is not None


@unittest.skipUnless(_have_node(), "node is not available in PATH")
class TestTimeoutsHelper(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="timeouts-helper-")
        shutil.copy(HELPER_PATH, str(Path(self.tmpdir) / "timeouts.js"))
        utils = Path(self.tmpdir) / "personas" / "utils"
        utils.mkdir(parents=True)
        shutil.copy(NETWORK_PATH, str(utils / "network.js"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _node(self, expr, env):
        script = textwrap.dedent(
            f"""
            const t = require("./timeouts");
            process.stdout.write("RESULT:" + JSON.stringify({expr}) + "\\n");
            """
        )
        script_path = str(Path(self.tmpdir) / "run.js")
        with Path(script_path).open("w") as f:
            f.write(script)
        return subprocess.run(
            ["node", "run.js"],
            capture_output=True,
            text=True,
            env={**os.environ, "PLAYWRIGHT_NETWORK_SUFFIXES": SUFFIXES, **env},
            cwd=self.tmpdir,
            timeout=10,
            check=False,
        )

    def _run(self, expr, env):
        proc = self._node(expr, env)
        self.assertEqual(
            proc.returncode, 0, msg=f"stderr={proc.stderr}\nstdout={proc.stdout}"
        )
        return proc.stdout

    def test_clearnet_default_factor_is_identity(self):
        out = self._run(
            "t.resolveTimeout(60000)",
            {"CANONICAL_DOMAIN": f'"x.{DOMAIN}"'},
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
            {
                "CANONICAL_DOMAIN": f"x.{DOMAIN}",
                "PLAYWRIGHT_TIMEOUT_FACTOR": "2",
            },
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
            {
                "CANONICAL_DOMAIN": f"x.{DOMAIN}",
                "PLAYWRIGHT_TIMEOUT_FACTOR": "0",
            },
        )
        self.assertIn("RESULT:60000", out)

    def test_a_waiter_may_not_outlive_the_suite_that_contains_it(self):
        """The onion run that starved web-app-docs: base 2_700_000 at
        multiplier 2 asked for 5_400_000 against a 5_340_000 suite budget, so
        the global timeout fired first and every remaining spec was reported
        "did not run" without naming the waiter."""
        out = self._run(
            "t.resolveTimeout(2700000) + ':' + t.SUITE_RESERVE_MS",
            {
                "CANONICAL_DOMAIN": '"docs.abc123.onion"',
                "PLAYWRIGHT_TIMEOUT_FACTOR": "1",
                "PLAYWRIGHT_ONION_TIMEOUT_MULTIPLIER": "2",
                "INFINITO_PLAYWRIGHT_GLOBAL_TIMEOUT_MS": "5340000",  # nocheck: the playwright role passes this into the sidecar container, it is not a .env key
            },
        )
        capped, reserve = out.split("RESULT:")[1].strip().strip('"').split(":")
        self.assertEqual(int(capped), 5340000 - int(reserve))

    def test_a_timeout_inside_the_budget_is_left_alone(self):
        out = self._run(
            "t.resolveTimeout(30000)",
            {
                "CANONICAL_DOMAIN": '"docs.abc123.onion"',
                "PLAYWRIGHT_ONION_TIMEOUT_MULTIPLIER": "2",
                "INFINITO_PLAYWRIGHT_GLOBAL_TIMEOUT_MS": "5340000",  # nocheck: the playwright role passes this into the sidecar container, it is not a .env key
            },
        )
        self.assertIn("RESULT:60000", out)

    def test_without_a_declared_budget_nothing_is_capped(self):
        out = self._run(
            "t.resolveTimeout(5400000)",
            {"CANONICAL_DOMAIN": '"x.infinito.test"'},
        )
        self.assertIn("RESULT:5400000", out)

    def test_is_onion_target_detects_quoted_and_bare(self):
        self.assertIn(
            "RESULT:true",
            self._run("t.isOnionTarget()", {"CANONICAL_DOMAIN": '"x.abc.onion"'}),
        )
        self.assertIn(
            "RESULT:true",
            self._run("t.isOnionTarget()", {"CANONICAL_DOMAIN": "x.abc.onion"}),
        )
        self.assertIn(
            "RESULT:false",
            self._run("t.isOnionTarget()", {"CANONICAL_DOMAIN": f'"x.{DOMAIN}"'}),
        )

    def test_is_onion_target_reads_app_base_url_first(self):
        self.assertIn(
            "RESULT:true",
            self._run("t.isOnionTarget()", {"APP_BASE_URL": '"https://x.abc.onion/"'}),
        )
        self.assertIn(
            "RESULT:false",
            self._run(
                "t.isOnionTarget()",
                {
                    "APP_BASE_URL": f'"https://x.{DOMAIN}/"',
                    "CANONICAL_DOMAIN": '"x.abc.onion"',
                },
            ),
        )

    def test_a_split_realm_is_a_clearnet_target_with_a_tor_issuer(self):
        issuer = '"https://auth.abc.onion/realms/main"'
        cases = (
            (f'"https://x.{DOMAIN}/"', issuer, "true"),
            ('"https://x.abc.onion/"', issuer, "false"),
            (f'"https://x.{DOMAIN}/"', f'"https://auth.{DOMAIN}/realms/main"', "false"),
            (f'"https://x.{DOMAIN}/"', "", "false"),
        )
        for base_url, issuer_url, expected in cases:
            with self.subTest(base_url=base_url, issuer_url=issuer_url):
                self.assertIn(
                    f"RESULT:{expected}",
                    self._run(
                        "t.isSplitRealmOidc()",
                        {"APP_BASE_URL": base_url, "OIDC_ISSUER_URL": issuer_url},
                    ),
                )

    def test_a_run_without_the_suffix_table_fails_loudly(self):
        proc = self._node(
            "t.isOnionTarget()",
            {"CANONICAL_DOMAIN": '"x.abc.onion"', "PLAYWRIGHT_NETWORK_SUFFIXES": ""},
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("PLAYWRIGHT_NETWORK_SUFFIXES is missing", proc.stderr)


if __name__ == "__main__":
    unittest.main()
