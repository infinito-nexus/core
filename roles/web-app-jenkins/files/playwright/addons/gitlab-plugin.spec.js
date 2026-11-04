const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { fetchPluginRecord, loginAsAdministrator } = require("../jenkins-login");

test.use({ ignoreHTTPSErrors: true });

test("addon gitlab-plugin: the GitLab plugin is installed and active", async ({ page }) => {
  skipUnlessAddonEnabled("gitlab-plugin");
  skipUnlessServiceEnabled("gitlab");
  test.setTimeout(resolveTimeout(180_000));

  await loginAsAdministrator(page);

  const plugin = await fetchPluginRecord(page, "gitlab-plugin");
  expect(
    plugin,
    "the plugin manager must list 'gitlab-plugin'; it is absent when the addon declaration did " +
      "not reach templates/plugins.txt.j2 and jenkins-plugin-cli never fetched it",
  ).toBeTruthy();
  expect(plugin.active, "the GitLab plugin must be active, not merely downloaded").toBe(true);
  expect(plugin.enabled, "the GitLab plugin must be enabled in the controller").toBe(true);
});
