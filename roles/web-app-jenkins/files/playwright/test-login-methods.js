const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { gotoOnion, normalizeBaseUrl } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

const baseUrl = normalizeBaseUrl(process.env.JENKINS_BASE_URL || "").replace(/\/$/, "");

test("login methods: with sso on the Jenkins sign-in hands over to Keycloak without a local form", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  expect(baseUrl, "JENKINS_BASE_URL must be set").toBeTruthy();
  await page.context().clearCookies();
  await gotoOnion(page, `${baseUrl}/login`, { waitUntil: "domcontentloaded" });
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: "the oic security realm must send /login to Keycloak instead of the j_username form",
    })
    .toContain("/protocol/openid-connect/auth");
  await expect(page.locator("input[name='j_password']"), "the local realm form must not render").toHaveCount(0);
});
