const { test, expect } = require("@playwright/test");

const { assertDesignTokens, assertReadable, captureDesignGallery, galleryEnabled } = require("./design");
const { decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

function baseUrl() {
  return decodeDotenvQuotedValue(process.env.APP_BASE_URL).replace(/\/$/, "");
}

exports.register = function (shared) {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await shared.loginToStandaloneNextcloud(page);
    await assertDesignTokens(page, "nextcloud");
  });

  test("design: Nextcloud theming carries the palette, the logo and the name", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const base = baseUrl();
    const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL);
    const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE);

    await page.emulateMedia({ colorScheme: "light" });
    await shared.loginToStandaloneNextcloud(page);
    await gotoOnion(page, `${base}/apps/dashboard/`);
    await shared.dismissBlockingNextcloudModals(page, page);
    const colors = await page.evaluate(() => {
      const resolve = (value) => {
        const probe = document.createElement("span");
        probe.style.color = value;
        document.body.appendChild(probe);
        const color = getComputedStyle(probe).color;
        probe.remove();
        return color;
      };
      return { theming: resolve("var(--color-primary)"), palette: resolve("var(--design-primary)") };
    });
    expect(colors.theming, "Nextcloud's theming primary must be the palette primary").toBe(colors.palette);
    await expect(page).toHaveTitle(new RegExp(title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    await page.emulateMedia({ colorScheme: null });
    await page.addStyleTag({ content: "*, *::before, *::after { transition: none !important; }" });
    const readable = ["h2", "a", "button"];
    for (const selector of readable) {
      await expect(page.locator(selector).first(), `nextcloud: '${selector}' must be on the dashboard`).toBeVisible();
    }
    await assertReadable(page, readable, "nextcloud");

    if (logoUrl) {
      const served = await page.request.get(`${base}/apps/theming/image/logo`);
      const generated = await page.request.get(logoUrl);
      expect(served.ok(), "Nextcloud serves a theming logo").toBe(true);
      expect(generated.ok(), "the generated logo is published on the CDN").toBe(true);
      expect(
        Buffer.compare(await served.body(), await generated.body()),
        "Nextcloud must serve the generated corporate logo",
      ).toBe(0);
    }
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
