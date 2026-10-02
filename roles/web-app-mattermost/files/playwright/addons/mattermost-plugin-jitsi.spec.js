const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { activePluginIds } = require("./_plugins");

const PLUGIN_ID = "jitsi";

test.use({ ignoreHTTPSErrors: true });

test("addon mattermost-plugin-jitsi: the Jitsi plugin is installed and active", async ({ page }) => {
  skipUnlessAddonEnabled("mattermost-plugin-jitsi");
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(240_000));

  const active = await activePluginIds(page);

  expect(
    active,
    `${PLUGIN_ID} must be among the active plugins; its absence means the marketplace install in tasks/utils/addon.yml was skipped or refused and no /jitsi command is registered`,
  ).toContain(PLUGIN_ID);
});
