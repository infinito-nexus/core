const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { fetchPluginRecord, loginAsAdministrator } = require("../jenkins-login");

test.use({ ignoreHTTPSErrors: true });

test("addon gitea: the Gitea plugin is installed and active", async ({ page }) => {
  skipUnlessAddonEnabled("gitea");
  skipUnlessServiceEnabled("gitea");
  test.setTimeout(resolveTimeout(180_000));

  await loginAsAdministrator(page);

  const plugin = await fetchPluginRecord(page, "gitea");
  expect(
    plugin,
    "the plugin manager must list 'gitea'; it is absent when the addon declaration did not " +
      "reach templates/plugins.txt.j2 and jenkins-plugin-cli never fetched it",
  ).toBeTruthy();
  expect(plugin.active, "the Gitea plugin must be active, not merely downloaded").toBe(true);
  expect(plugin.enabled, "the Gitea plugin must be enabled in the controller").toBe(true);
});
