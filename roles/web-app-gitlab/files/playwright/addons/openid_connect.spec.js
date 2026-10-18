const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { gotoOnion, normalizeBaseUrl } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

test("addon openid_connect: the sign-in page offers the OmniAuth provider the role renders into gitlab.yml", async ({ page }) => {
  skipUnlessAddonEnabled("openid_connect");
  skipUnlessServiceEnabled("sso");

  const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();

  const response = await gotoOnion(page, `${appBaseUrl}/users/sign_in`, { waitUntil: "domcontentloaded" });
  expect(response, "Expected a response from the GitLab sign-in page").toBeTruthy();
  expect(response.status(), "Expected the GitLab sign-in page status < 400").toBeLessThan(400);

  const providerEntry = page
    .locator("form[action*='/users/auth/openid_connect']")
    .or(page.locator("a[href*='/users/auth/openid_connect']"))
    .first();
  await expect(
    providerEntry,
    "the sign-in page must offer the openid_connect OmniAuth entry point; its absence means the omniauth provider block in templates/config/gitlab.yml.j2 never reached the running webservice",
  ).toBeAttached({ timeout: resolveTimeout(30_000) });
});
