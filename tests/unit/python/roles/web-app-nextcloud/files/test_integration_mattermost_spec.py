from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from . import PROJECT_ROOT

SPEC = (
    PROJECT_ROOT
    / "roles"
    / "web-app-nextcloud"
    / "files"
    / "playwright"
    / "addons"
    / "integration_mattermost.spec.js"
)
NEXTCLOUD_URL = "https://next.cloud.example.test/"
AUTHORIZE_URL = (
    "https://chat.example.test/oauth/authorize?client_id=uid&response_type=code&state=s"
)

PLAYWRIGHT_STUB = textwrap.dedent(
    """
    const registered = [];
    function test(title, fn) {
      registered.push({ title, fn });
    }
    test.setTimeout = () => {};
    function expect(actual, message) {
      const check = (ok, what) => {
        if (!ok) {
          throw new Error(`${message || ""} (${what})`);
        }
      };
      const matchers = {
        toBeVisible: async () => {},
        toMatch: (pattern) => check(pattern.test(String(actual)), `expected ${actual} to match ${pattern}`),
        toBe: (value) => check(actual === value, `expected ${value}, got ${actual}`),
      };
      matchers.not = {
        toBe: (value) => check(actual !== value, `expected not ${value}`),
      };
      return matchers;
    }
    expect.poll = (fn) => ({
      toMatch: async (pattern) => {
        const value = await fn();
        if (!pattern.test(String(value))) {
          throw new Error(`poll: expected ${value} to match ${pattern}`);
        }
      },
    });
    module.exports = { test, expect, registered };
    """
)

SHARED_STUB = textwrap.dedent(
    """
    const scenario = JSON.parse(process.env.SCENARIO);
    module.exports = {
      env: { nextcloudBaseUrl: scenario.nextcloud_url },
      loginToStandaloneNextcloud: async () => {},
      dismissBlockingNextcloudModals: async () => {},
      clickWithModalRetry: async (page, _frame, target) => {
        if (scenario.retry_dismisses) page.dismissWizard();
        return target.click();
      },
    };
    """
)

PERSONAS_STUB = "module.exports = { gotoOnion: async (page, url) => page.goto(url) };\n"
GATING_STUB = "module.exports = { skipUnlessAddonEnabled: () => {} };\n"
TIMEOUTS_STUB = "module.exports = { resolveTimeout: (ms) => ms };\n"

DRIVER = textwrap.dedent(
    """
    const { registered } = require("@playwright/test");
    require("./addons/integration_mattermost.spec.js");
    const scenario = JSON.parse(process.env.SCENARIO);
    const entry = registered.find((t) => t.title.startsWith("integration integration_mattermost:"));
    const state = { url: "about:blank", wizardOpen: false };
    const navigated = [];
    const connect = {
      or: () => connect,
      first: () => connect,
      click: async () => {
        if (state.wizardOpen) {
          throw new Error('locator.click: <div id="firstrunwizard"> subtree intercepts pointer events');
        }
        state.url = scenario.authorize_url;
        navigated.splice(0).forEach((resolve) => resolve());
      },
    };
    const page = {
      goto: async (url) => {
        state.url = url;
        if (scenario.wizard) state.wizardOpen = true;
      },
      dismissWizard: () => {
        state.wizardOpen = false;
      },
      locator: () => connect,
      getByRole: () => connect,
      waitForLoadState: async () => {},
      waitForEvent: (kind) =>
        kind === "framenavigated"
          ? new Promise((resolve) => navigated.push(resolve))
          : Promise.reject(new Error(`waiting for ${kind}: Timeout exceeded`)),
      url: () => state.url,
      close: async () => {},
    };
    const browser = { newContext: async () => ({ newPage: async () => page, close: async () => {} }) };
    entry.fn({ browser }).then(
      () => process.stdout.write("RAN\\n"),
      (error) => process.stdout.write(`ERROR:${error.message}\\n`),
    );
    """
)


def _have_node() -> bool:
    return shutil.which("node") is not None


@unittest.skipUnless(_have_node(), "node is not available in PATH")
class TestMattermostConnectSurvivesFirstRunWizard(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stub = self.root / "node_modules" / "@playwright" / "test"
        stub.mkdir(parents=True)
        (stub / "package.json").write_text(
            json.dumps({"name": "@playwright/test", "main": "index.js"})
        )
        (stub / "index.js").write_text(PLAYWRIGHT_STUB)
        (self.root / "_shared.js").write_text(SHARED_STUB)
        (self.root / "personas.js").write_text(PERSONAS_STUB)
        (self.root / "addon-gating.js").write_text(GATING_STUB)
        (self.root / "timeouts.js").write_text(TIMEOUTS_STUB)
        (self.root / "run.js").write_text(DRIVER)
        (self.root / "addons").mkdir()
        shutil.copy(SPEC, self.root / "addons" / "integration_mattermost.spec.js")

    def _run(self, wizard: bool, retry_dismisses: bool) -> str:
        """Args:
            wizard: whether the first-run wizard covers the page after every navigation.
            retry_dismisses: whether the shared modal-retry click dismisses the wizard.

        Returns:
            The driver's stdout: RAN or ERROR:<message>.
        """
        scenario = {
            "nextcloud_url": NEXTCLOUD_URL,
            "authorize_url": AUTHORIZE_URL,
            "wizard": wizard,
            "retry_dismisses": retry_dismisses,
        }
        proc = subprocess.run(
            ["node", "run.js"],
            capture_output=True,
            text=True,
            env={**os.environ, "SCENARIO": json.dumps(scenario)},
            cwd=self.root,
            timeout=30,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def test_connect_without_wizard_reaches_the_partner_authorize(self) -> None:
        self.assertIn("RAN", self._run(wizard=False, retry_dismisses=False))

    def test_connect_click_dismisses_a_late_first_run_wizard(self) -> None:
        self.assertIn("RAN", self._run(wizard=True, retry_dismisses=True))

    def test_negative_control_an_undismissed_wizard_fails_on_its_interception(
        self,
    ) -> None:
        out = self._run(wizard=True, retry_dismisses=False)
        self.assertIn("ERROR:", out)
        self.assertIn("firstrunwizard", out)
        self.assertIn("intercepts pointer events", out)


if __name__ == "__main__":
    unittest.main()
