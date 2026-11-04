const { test, expect } = require("./fixtures/onion-test");
const { resolveTimeout } = require("./timeouts");

const { decodeDotenvQuotedValue, gotoOnion } = require("./personas");

const platformLogoUrl = decodeDotenvQuotedValue(process.env.PLATFORM_LOGO_URL);
const platformFaviconUrl = decodeDotenvQuotedValue(process.env.PLATFORM_FAVICON_URL);
const platformTitle = decodeDotenvQuotedValue(process.env.PLATFORM_TITLE);

async function getCurrentImageSource(locator) {
  return locator.evaluate((img) => img.currentSrc || img.src || "");
}

async function expectImageLoaded(locator, label, expectedUrl) {
  await expect(locator).toBeVisible({ timeout: resolveTimeout(60_000) });

  await expect
    .poll(() => locator.evaluate((img) => img.complete && img.naturalWidth > 0), {
      timeout: resolveTimeout(60_000),
      message: `${label} never finished decoding`,
    })
    .toBe(true);

  const loaded = await locator.evaluate((img) => ({
    source: img.currentSrc || img.src || "",
    naturalWidth: img.naturalWidth,
  }));

  // port-ui >= 2.0.0's probe-first resolver embeds reachable image URLs
  // directly, so the rendered src is the asset URL Ansible computed and
  // passed via PLATFORM_LOGO_URL — assert the exact value rather than a
  // shape regex so a regression in the resolver is loud.
  expect(loaded.source, `${label} should render the resolved platform logo URL`).toBe(expectedUrl);
  expect(loaded.naturalWidth, `${label} should resolve to a non-empty dashboard image asset`).toBeGreaterThan(0);
}

exports.register = function (shared) {
  test("dashboard loads role-core JavaScript modules and renders header/navbar logos", async ({ page }) => {
    shared.skipUnlessServiceEnabled("cdn");
    test.skip(
      !shared.isServiceEnabled("asset") && !shared.isServiceEnabled("design"),
      "neither the asset service nor the corporate design provides the platform logo"
    );

    const diagnostics = shared.attachDiagnostics(page);
    const documentResponse = await gotoOnion(page,"/");
    expect(documentResponse.status()).toBeLessThan(400);

    const documentHtml = await documentResponse.text();
    await shared.waitForDashboardReady(page);
    await shared.waitForResourceResponse(diagnostics.responses, `${shared.env.dashboardJsBaseUrl}/iframe.js`, "dashboard iframe sync script");

    expect(documentHtml).toContain("loadScriptSequential");
    expect(documentHtml).toContain(shared.env.dashboardJsBaseUrl);
    expect(documentHtml).toContain('"iframe.js"');

    if (shared.isServiceEnabled("sso")) {
      await shared.waitForResourceResponse(diagnostics.responses, `${shared.env.dashboardJsBaseUrl}/oidc.js`, "dashboard oidc script");
      expect(documentHtml).toContain('"oidc.js"');
    }

    const headerLogo = page.locator("header.header img[alt='logo']").first();
    const navbarLogo = page.locator("#navbar_logo img").first();
    await expectImageLoaded(headerLogo, "Header logo", platformLogoUrl);
    await expectImageLoaded(navbarLogo, "Navbar logo", platformLogoUrl);
    expect(await getCurrentImageSource(headerLogo)).toBe(await getCurrentImageSource(navbarLogo));
    await expect(page.locator("header.header h1").first()).toHaveText(platformTitle);

    // Favicon — a <link rel="icon"> is not "visible" in Playwright's sense,
    // so just assert that its href is the resolved PLATFORM_FAVICON_URL.
    const faviconHref = await page.locator('link[rel="icon"]').first().getAttribute("href");
    expect(faviconHref, "favicon link should render the resolved platform favicon URL").toBe(
      platformFaviconUrl
    );
  });
};
