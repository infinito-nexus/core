const { test } = require("@playwright/test");

const { assertDesignTokens, captureDesignGallery, galleryEnabled } = require("./design");
const { decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

function baseUrl() {
  return decodeDotenvQuotedValue(process.env.APP_BASE_URL).replace(/\/$/, "");
}

exports.register = function (shared) {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await gotoOnion(page, `${baseUrl()}/login`);
    await assertDesignTokens(page, "nextcloud");
  });

  test("design: gallery of user and administration views", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(900_000));
    const base = baseUrl();
    const settle = (p) => shared.dismissBlockingNextcloudModals(p, p);

    await captureDesignGallery(page, [{ name: "login", url: `${base}/login` }]);

    await shared.loginToStandaloneNextcloud(page);
    await settle(page);

    const views = [
      ["dashboard", "/apps/dashboard/"],
      ["files", "/apps/files/"],
      ["activity", "/apps/activity/"],
      ["settings-personal", "/settings/user"],
      ["settings-security", "/settings/user/security"],
      ["settings-notifications", "/settings/user/notifications"],
      ["settings-appearance", "/settings/user/theming"],
      ["settings-sharing", "/settings/user/sharing"],
      ["settings-privacy", "/settings/user/privacy"],
      ["settings-sync-clients", "/settings/user/sync-clients"],
      ["settings-availability", "/settings/user/availability"],
      ["admin-overview", "/settings/admin/overview"],
      ["admin-basic", "/settings/admin"],
      ["admin-sharing", "/settings/admin/sharing"],
      ["admin-security", "/settings/admin/security"],
      ["admin-theming", "/settings/admin/theming"],
      ["admin-groupware", "/settings/admin/groupware"],
      ["admin-logging", "/settings/admin/logging"],
      ["users", "/settings/users"],
      ["apps", "/settings/apps"],
      ["help", "/settings/help"],
    ];
    await captureDesignGallery(
      page,
      views.map(([name, path]) => ({ name, url: `${base}${path}`, prepare: settle })),
    );
  });
};
