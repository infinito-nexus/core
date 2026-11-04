const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { activePluginIds } = require("./_plugins");

const PLUGIN_ID = "mattermost-ai";

test.use({ ignoreHTTPSErrors: true });

test("addon mattermost-plugin-agents: the prepackaged Agents plugin is active", async ({ page }) => {
  skipUnlessAddonEnabled("mattermost-plugin-agents");
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(240_000));

  const active = await activePluginIds(page);

  expect(
    active,
    `${PLUGIN_ID} must be among the active plugins; the plugin ships with the image, so its absence means the enable step in tasks/utils/addon.yml never ran`,
  ).toContain(PLUGIN_ID);
});
