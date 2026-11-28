import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from . import PROJECT_ROOT

KEYCLOAK = PROJECT_ROOT / "roles/test-e2e-playwright/files/personas/utils/keycloak.js"
INTERNALS = PROJECT_ROOT / "tests/unit/javascript/utils/internals.js"

DRIVER = textwrap.dedent(
    """
    const { loadInternals } = require(process.env.INTERNALS);
    const expect = {
      poll: (probe) => ({
        toBe: async (expected) => {
          if (probe() !== expected) throw new Error(`poll: expected ${expected}`);
        },
      }),
    };
    const { settleSsoChain } = loadInternals(
      process.env.KEYCLOAK,
      ["settleSsoChain"],
      { "@playwright/test": { expect }, "../../timeouts": { resolveTimeout: (ms) => ms } },
      {},
    );
    const closesDuringWait = process.env.SCENARIO === "closes";
    let closed = false;
    const popup = {
      url: () => "https://espocrm.example.test/oauth-callback.php?code=probe",
      isClosed: () => closed,
      waitForLoadState: async () => {
        closed = closesDuringWait;
        throw new Error(
          closesDuringWait
            ? "page.waitForLoadState: Target page, context or browser has been closed"
            : "page.waitForLoadState: Timeout 30000ms exceeded.",
        );
      },
    };
    settleSsoChain(popup, { failedUrl: "" }).then(
      () => process.stdout.write("SETTLED\\n"),
      (error) => process.stdout.write(`ERROR:${error.message}\\n`),
    );
    """
)


def _have_node() -> bool:
    return shutil.which("node") is not None


@unittest.skipUnless(_have_node(), "node is not available in PATH")
class TestSettleSsoChainToleratesASelfClosingPopup(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "run.js").write_text(DRIVER)

    def _run(self, scenario: str) -> str:
        """Args:
            scenario: `closes` closes the popup during the load-state wait, as EspoCRM's sign-in popup does; `open` fails the wait on a page that stays open.

        Returns:
            The driver's stdout: SETTLED or ERROR:<message>.
        """
        proc = subprocess.run(
            ["node", "run.js"],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "SCENARIO": scenario,
                "KEYCLOAK": str(KEYCLOAK),
                "INTERNALS": str(INTERNALS),
            },
            cwd=self.root,
            timeout=30,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def test_a_popup_closing_during_the_load_state_wait_counts_as_settled(
        self,
    ) -> None:
        self.assertIn("SETTLED", self._run("closes"))

    def test_negative_control_a_failed_wait_on_an_open_page_still_rejects(
        self,
    ) -> None:
        out = self._run("open")
        self.assertIn("ERROR:", out)
        self.assertIn("Timeout 30000ms exceeded", out)


if __name__ == "__main__":
    unittest.main()
