const { test, expect } = require("@playwright/test");
const { resolveTimeout, isSplitRealmOidc } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { gotoOnion, normalizeBaseUrl, requireDotenvValue } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

function appBase() {
  return normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
}

function registrationEnabled() {
  return (
    requireDotenvValue(process.env.LOGIN_METHOD_REGISTRATION_ENABLED, "LOGIN_METHOD_REGISTRATION_ENABLED") === "true"
  );
}

test("login methods: with sso on, XWiki hands the sign-in to Keycloak and offers no local entry", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  test.skip(isSplitRealmOidc(), "clearnet app with an onion OIDC issuer: unreachable from one browser");
  const base = appBase();
  const issuer = new URL(requireDotenvValue(process.env.OIDC_ISSUER_URL, "OIDC_ISSUER_URL"));
  await page.context().clearCookies();

  await gotoOnion(page, `${base}/bin/view/Main/`, { waitUntil: "domcontentloaded" });
  await expect(page.locator("#xwikicontent")).toBeVisible({ timeout: resolveTimeout(60_000) });
  if (!registrationEnabled()) {
    await expect(
      page.locator("a[href*='/bin/register/']"),
      "with registration off the guest MUST NOT see XWiki's Register entry",
    ).toHaveCount(0);
    await gotoOnion(page, `${base}/bin/register/XWiki/XWikiRegister`, { waitUntil: "domcontentloaded" });
    await expect(
      page.locator("input[name='register_password']"),
      "with registration off XWiki MUST refuse the guest its registration form",
    ).toHaveCount(0);
  }

  await gotoOnion(page, `${base}/bin/login/XWiki/XWikiLogin`, { waitUntil: "domcontentloaded" });
  await page.waitForURL(/\/protocol\/openid-connect\/auth/, { timeout: resolveTimeout(60_000) });
  expect(
    new URL(page.url()).hostname,
    "the XWiki sign-in MUST hand off to the Keycloak issuer instead of rendering a local form",
  ).toBe(issuer.hostname);
  await expect(page.locator("#j_password"), "no XWiki password form may sit on the SSO path").toHaveCount(0);
});

test("break-glass: superadmin signs in through the local form behind oidc.skipped while sso is on", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  const base = appBase();
  const username = requireDotenvValue(process.env.XWIKI_SUPERADMIN_USERNAME, "XWIKI_SUPERADMIN_USERNAME");
  const password = requireDotenvValue(process.env.XWIKI_SUPERADMIN_PASSWORD, "XWIKI_SUPERADMIN_PASSWORD");
  await page.context().clearCookies();

  await gotoOnion(page, `${base}/bin/login/XWiki/XWikiLogin?oidc.skipped=true`, { waitUntil: "domcontentloaded" });
  await expect(
    page.locator("#j_username"),
    "oidc.skipped=true MUST keep XWiki's local form reachable as the break-glass path",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
  await page.locator("#j_username").fill(username);
  await page.locator("#j_password").fill(password);
  await page.locator("#loginForm input[type='submit']").click();
  await expect(page.locator("html")).toHaveAttribute("data-xwiki-user-reference", new RegExp(`XWiki\\.${username}$`, "i"), {
    timeout: resolveTimeout(60_000),
  });
});
