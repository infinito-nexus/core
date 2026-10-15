const { test, expect } = require("@playwright/test");

const {
  assertDesignTokens,
  assertLightAndDark,
  assertReadable,
  captureDesignGallery,
  galleryEnabled,
  tokenValue,
} = require("./design");
const { apiFetchOnion, apiGetOnion, decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

function baseUrl() {
  return decodeDotenvQuotedValue(process.env.APP_BASE_URL).replace(/\/$/, "");
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function assertShownLogo(page, selector, key, logoUrl) {
  const generated = await apiGetOnion(page.request, logoUrl);
  expect(generated.ok(), "the generated logo is published on the CDN").toBe(true);
  const logo = page.locator(selector);
  await expect(logo).toBeVisible({ timeout: resolveTimeout(30_000) });
  const box = await logo.boundingBox();
  expect(box.width > 0 && box.height > 0, `${selector} has a box`).toBe(true);
  const image = await logo.evaluate((element) => getComputedStyle(element).backgroundImage);
  expect(image, `${selector} shows the theming ${key}`).toContain(`/apps/theming/image/${key}`);
  const href = image.match(/url\("?([^")]+)"?\)/)[1];
  const served = await apiGetOnion(page.request, new URL(href, `${baseUrl()}/`).toString());
  expect(served.ok(), `${selector}: Nextcloud serves its ${key}`).toBe(true);
  expect(Buffer.compare(await served.body(), await generated.body()), `${selector} shows the generated logo`).toBe(0);
}

exports.register = function (shared) {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await shared.loginToStandaloneNextcloud(page);
    await assertDesignTokens(page, "nextcloud");
  });

  test("design: Nextcloud theming carries the palette and the name", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const base = baseUrl();
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
    await expect(page, "the configured name closes the page title").toHaveTitle(new RegExp(`- ${escapeRegExp(title)}$`));
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, ["h2", "a", "button"], "nextcloud");

    await gotoOnion(page, `${base}/apps/files/`);
    await shared.dismissBlockingNextcloudModals(page, page);
    await assertLightAndDark(page, "main", "nextcloud");
  });

  test("design: the theme picker of Nextcloud drives its own theme and the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.setTimeout(resolveTimeout(300_000));
    const base = baseUrl();
    const html = page.locator("html");
    const mainBackground = () =>
      page.evaluate(() => getComputedStyle(document.body).getPropertyValue("--color-main-background").trim());
    const pick = async (id) => {
      await gotoOnion(page, `${base}/settings/user/theming`);
      await shared.dismissBlockingNextcloudModals(page, page);
      const card = page.locator(`.theming__preview--${id}`);
      await expect(card).toBeVisible({ timeout: resolveTimeout(30_000) });
      const current = await page.evaluate(() => (document.body.getAttribute("data-themes") || "").split(","));
      if (current.includes(id)) return;
      const stored = page.waitForResponse(
        (response) =>
          response.url().includes(`/apps/theming/api/v1/theme/${id}/enable`) && response.request().method() === "PUT",
        { timeout: resolveTimeout(30_000) },
      );
      await card.locator(".theming__preview-image").click();
      expect((await stored).ok(), `Nextcloud stores the ${id} theme`).toBe(true);
    };
    const restoreDefault = () =>
      apiFetchOnion(page.request, `${base}/ocs/v2.php/apps/theming/api/v1/theme/default/enable`, {
        method: "PUT",
        headers: { "OCS-APIRequest": "true" },
      });

    await page.emulateMedia({ colorScheme: "light" });
    await shared.loginToStandaloneNextcloud(page);
    try {
      await pick("default");
      const lightSurface = await tokenValue(page, "--design-surface-1", "color");
      const lightBackground = await mainBackground();
      await pick("dark");
      await expect(page.locator("body")).toHaveAttribute("data-themes", /(^|,)dark(,|$)/);
      await expect(html, "a dark pick pins the palette to dark").toHaveAttribute("data-design-theme", "dark");
      await gotoOnion(page, `${base}/apps/files/`);
      await shared.dismissBlockingNextcloudModals(page, page);
      await expect(html, "the pick is stored for the account").toHaveAttribute("data-design-theme", "dark");
      expect(await tokenValue(page, "--design-surface-1", "color"), "the tokens follow the pick").not.toBe(lightSurface);
      expect(await mainBackground(), "Nextcloud renders its dark theme").not.toBe(lightBackground);
      await assertReadable(page, ["#app-navigation-vue a", "#app-content-vue h2, #app-content-vue button"], "nextcloud dark pick");
      await page.emulateMedia({ colorScheme: "dark" });
      await pick("light");
      await expect(html, "a light pick pins the palette to light").toHaveAttribute("data-design-theme", "light");
      expect(await tokenValue(page, "--design-surface-1", "color")).toBe(lightSurface);
      expect(await mainBackground()).toBe(lightBackground);
    } finally {
      await pick("default").catch(restoreDefault);
      await page.emulateMedia({ colorScheme: null });
    }
    await expect(html, "the automatic theme leaves the palette to the browser").not.toHaveAttribute("data-design-theme");
  });

  test("design: the admin theming settings show the configured name, color and images", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.setTimeout(resolveTimeout(180_000));
    const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE);
    const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL);

    await page.emulateMedia({ colorScheme: "light" });
    await shared.loginToStandaloneNextcloud(page);
    await gotoOnion(page, `${baseUrl()}/settings/admin/theming`);
    await shared.dismissBlockingNextcloudModals(page, page);
    const section = page.locator("[data-admin-theming-settings]");
    await expect(section).toBeVisible({ timeout: resolveTimeout(30_000) });
    await expect(section.getByRole("textbox", { name: "Name", exact: true })).toHaveValue(title);
    const primary = page.getByRole("button", { name: "Primary color", exact: true });
    const expected = await tokenValue(page, "--design-primary", "background-color");
    await expect
      .poll(() => primary.evaluate((element) => getComputedStyle(element).backgroundColor), {
        message: "the admin form shows the palette primary as Nextcloud's primary color",
      })
      .toBe(expected);
    if (logoUrl) {
      await expect(page.getByRole("img", { name: "Preview of the selected image" })).toHaveCount(3);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, "[data-admin-theming-settings]", "nextcloud admin theming");
    await assertReadable(
      page,
      ["[data-admin-theming-settings] h2", "[data-admin-theming-settings] label", "[data-admin-theming-settings] p"],
      "nextcloud admin theming",
    );
  });

  test("design: the header shows the generated logo", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL);
    test.skip(!logoUrl, "the logo replacement is disabled for this role");
    await shared.loginToStandaloneNextcloud(page);
    await gotoOnion(page, `${baseUrl()}/apps/dashboard/`);
    await shared.dismissBlockingNextcloudModals(page, page);
    await assertShownLogo(page, "#header #nextcloud .logo", "logoheader", logoUrl);
    await expect(page.locator("#header #nextcloud .logo"), "a custom header logo is never inverted").toHaveCSS(
      "filter",
      "none",
    );
  });

  test("design: the sign-in page shows the generated logo", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL);
    test.skip(!logoUrl, "the logo replacement is disabled for this role");
    test.skip(shared.env.nextcloudLoginFlavor === "oidc_login", "the sign-in page redirects to the identity provider");
    await gotoOnion(page, `${baseUrl()}/login`);
    await assertShownLogo(page, "#header.header-guest .logo", "logo", logoUrl);
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
