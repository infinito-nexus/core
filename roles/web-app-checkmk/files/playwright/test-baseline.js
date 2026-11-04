const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, runAdminFlow, runBiberFlow, runGuestFlow } = require("./personas");
const { isServiceEnabled } = require("./service-gating");
const { withBiberInGroup } = require("./_rbac");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");

test.beforeEach(async ({ page }) => {
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
});

test("Checkmk front surface is reachable under the canonical domain", async ({ page }) => {
  const response = await gotoOnion(page, `${appBaseUrl}/`);
  expect(response, "Expected a Checkmk front response").toBeTruthy();
  expect(response.status(), "Expected the Checkmk front status to be < 500").toBeLessThan(500);
});

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

test("biber: app → universal logout", async ({ page, browser }) => {
  if (!isServiceEnabled("sso")) {
    await runBiberFlow(page);
    return;
  }
  test.setTimeout(resolveTimeout(180_000)); // Keycloak group join plus the oauth2-proxy round-trip
  await withBiberInGroup(browser, decodeDotenvQuotedValue(process.env.RBAC_GUEST_GROUP_PATH), () => runBiberFlow(page));
});

test("administrator: app → admin surface → universal logout", async ({ page }) => {
  await runAdminFlow(page, {
    adminInteraction: async (interactivePage) => {
      const setup = interactivePage.locator("#popup_trigger_mega_menu_setup > a").first();
      if (await setup.isVisible().catch(() => false)) {
        await setup.click({ timeout: resolveTimeout(30_000) });
        await expect(
          interactivePage.locator("#popup_menu_setup"),
          "the Setup menu MUST open: Checkmk wires it through an inline onclick, which script-src-attr has to admit",
        ).toBeVisible({ timeout: resolveTimeout(30_000) });
      }
    },
  });
});
