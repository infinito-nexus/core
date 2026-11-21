const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { gotoOnion, normalizeBaseUrl } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

const base = normalizeBaseUrl(process.env.JOOMLA_BASE_URL).replace(/\/$/, "");
const passkeyEnabled = process.env.LOGIN_METHOD_PASSKEY_ENABLED === "true";
const registrationEnabled = process.env.LOGIN_METHOD_REGISTRATION_ENABLED === "true";
const PASSKEY_BUTTON = "button[class*='webauthn']";
const REGISTRATION_LINK = "a[href*='view=registration'], a[href*='/users/registration']";
const ACTION = { timeout: resolveTimeout(60_000) };

/**
 * Args:
 *   page: Playwright page on a Joomla sign-in form.
 *   selector: the entry of a sign-in method.
 *   enabled: whether login.method switches that method on.
 *   label: the method, named in the failure message.
 */
async function expectEntry(page, selector, enabled, label) {
  if (enabled) {
    await expect(page.locator(selector).first(), `${label} is on, so its entry must render`).toBeVisible(ACTION);
  } else {
    await expect(page.locator(selector), `${label} is off, so its entry must not render`).toHaveCount(0);
  }
}

test("login methods: with sso on the site and the administrator hand a guest to Keycloak", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(180_000));
  for (const entry of [`${base}/index.php?option=com_users&view=login`, `${base}/administrator/`]) {
    await page.context().clearCookies();
    await gotoOnion(page, entry, { waitUntil: "domcontentloaded" });
    await expect
      .poll(() => page.url(), {
        timeout: resolveTimeout(60_000),
        message: `${entry} must send a guest to Keycloak instead of rendering a local form`,
      })
      .toContain("/protocol/openid-connect/auth");
  }
});

test("login methods: the ?fallback=local break-glass forms offer no switched-off entry", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(180_000));
  await page.context().clearCookies();

  await gotoOnion(page, `${base}/administrator/index.php?fallback=local`, { waitUntil: "domcontentloaded" });
  await expect(page.locator("#mod-login-username"), "the administrator break-glass form must render").toBeVisible(ACTION);
  await expectEntry(page, PASSKEY_BUTTON, passkeyEnabled, "login.method.passkey");

  await gotoOnion(page, `${base}/index.php?option=com_users&view=login&fallback=local`, { waitUntil: "domcontentloaded" });
  await expect(page.locator("main input[name='username']"), "the site break-glass form must render").toBeVisible(ACTION);
  await expectEntry(page, PASSKEY_BUTTON, passkeyEnabled, "login.method.passkey");
  await expectEntry(page, REGISTRATION_LINK, registrationEnabled, "login.method.registration");
  await page.context().clearCookies();
});
