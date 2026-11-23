from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

LOGOUT_FLOW = (
    PROJECT_ROOT
    / "roles"
    / "web-svc-logout"
    / "files"
    / "playwright"
    / "logout-flow.js"
)

ACCOUNT_URL = "https://auth.example.test/realms/main/account"
TOKEN_URL = "https://auth.example.test/realms/main/protocol/openid-connect/token"

STUBS = {
    "node_modules/@playwright/test/package.json": json.dumps(
        {"name": "@playwright/test", "main": "index.js"}
    ),
    "node_modules/@playwright/test/index.js": """
        module.exports = {
          expect: (value, message) => ({
            toBe: (expected) => {
              if (value !== expected) throw new Error(`${message}: ${value} is not ${expected}`);
            },
          }),
        };
    """,
    "personas/index.js": f"""
        const calls = [];
        const keycloak = (url, options) => {{
          if (url === "{TOKEN_URL}") return 200;
          if (!url.startsWith("{ACCOUNT_URL}/")) return 200;
          const accept = (options.headers || {{}}).Accept || "*/*";
          if (accept !== "application/json") return options.method === "GET" ? 200 : 405;
          return options.method === "DELETE" ? 204 : 200;
        }};
        module.exports = {{
          calls,
          OIDC_LOGIN_READY_FLAG: "__oidcLoginReady",
          apiFetchOnion: async (_request, url, options) => {{
            calls.push({{ url, method: options.method, headers: options.headers || {{}} }});
            const status = keycloak(url, options);
            return {{
              status: () => status,
              json: async () => (url === "{TOKEN_URL}" ? {{ access_token: "access", refresh_token: "refresh" }} : []),
            }};
          }},
          apiGetOnion: async () => null,
          clickOidcLoginLink: async () => null,
          decodeDotenvJsonList: (value) => (value ? JSON.parse(value) : []),
          decodeDotenvQuotedValue: (value) => value,
          gotoOnion: async () => null,
          performKeycloakLoginForm: async () => null,
          requireDotenvValue: (value) => value || "set",
        }};
    """,
    "personas/utils/network.js": "module.exports = { isTorUrl: () => false };",
    "timeouts.js": "module.exports = { isOnionTarget: () => false, resolveTimeout: (ms) => ms };",
    "run.js": f"""
        process.env.KEYCLOAK_ACCOUNT_URL = "{ACCOUNT_URL}";
        process.env.KEYCLOAK_TOKEN_URL = "{TOKEN_URL}";
        const {{ calls }} = require("./personas");
        const flow = require("./logout-flow");
        (async () => {{
          try {{
            await flow[process.argv[2]]({{}});
            process.stdout.write(JSON.stringify({{ calls }}));
          }} catch (error) {{
            process.stdout.write(JSON.stringify({{ calls, error: error.message }}));
          }}
        }})();
    """,
}


@unittest.skipUnless(shutil.which("node"), "node is not available in PATH")
class TestAccountRestHeaders(unittest.TestCase):
    def setUp(self) -> None:
        self.workdir = Path(tempfile.mkdtemp(prefix="logout-account-"))
        for relative, source in STUBS.items():
            target = self.workdir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("w") as handle:
                handle.write(textwrap.dedent(source))
        shutil.copy(str(LOGOUT_FLOW), str(self.workdir / "logout-flow.js"))

    def tearDown(self) -> None:
        shutil.rmtree(self.workdir, ignore_errors=True)

    def _run(self, function: str) -> dict:
        """Args:
            function: the exported logout-flow.js function to call.

        Returns:
            The requests it sent and the error it raised, if any.
        """
        proc = subprocess.run(
            ["node", "run.js", function],
            capture_output=True,
            text=True,
            cwd=str(self.workdir),
            timeout=20,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        return json.loads(proc.stdout)

    def _account_calls(self, result: dict) -> list[dict]:
        calls = [
            call for call in result["calls"] if call["url"].startswith(ACCOUNT_URL)
        ]
        self.assertTrue(calls, result)
        return calls

    def test_ending_every_other_session_reaches_the_rest_api(self) -> None:
        result = self._run("endEveryOtherSession")
        self.assertNotIn("error", result, result)
        for call in self._account_calls(result):
            self.assertEqual(
                call["headers"].get("Accept"),
                "application/json",
                "Keycloak hands a DELETE that does not accept JSON to the account "
                "console, which answers 405 and ends no session",
            )

    def test_listing_the_applications_reaches_the_rest_api(self) -> None:
        result = self._run("accountApplications")
        self.assertNotIn("error", result, result)
        for call in self._account_calls(result):
            self.assertEqual(call["headers"].get("Accept"), "application/json")


if __name__ == "__main__":
    unittest.main()
