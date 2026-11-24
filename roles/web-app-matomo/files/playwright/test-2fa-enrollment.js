const crypto = require("node:crypto");
const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { gotoOnion } = require("./personas");
const { totpCode } = require("./totp");
const {
  adminPassword,
  adminUsername,
  appBaseUrl,
  canonicalDomain,
  matomoApi,
  nativeLoginEnabled,
  seedVisits,
  signIn,
  twoFactorEnforced,
} = require("./_shared");

const REPORTS = `${appBaseUrl}/index.php?module=CoreHome&action=index&idSite=1&period=day&date=today`;
const CONFIRM = `${appBaseUrl}/index.php?module=TwoFactorAuth&action=onLoginSetupTwoFactorAuth`;
const SETUP = ".setupTwoFactorAuthentication";
const STANDALONE_SETUP = 'vue-entry="TwoFactorAuth.SetupTwoFactorAuth"';
const MENU = "#secondNavBar";
const SECRET = /new-secret="&quot;([A-Z2-7]+)&quot;"/;
const NONCE = /auth-code-nonce="&quot;([^&"]+)&quot;"/;

function probeAccount() {
  const login = `infinito-2fa-probe-${Date.now().toString(36)}${crypto.randomBytes(3).toString("hex")}`;
  return { login, password: `${crypto.randomBytes(18).toString("base64url")}Aa1!` };
}

/**
 * Args:
 *   request: the request fixture, which carries no session, so the token alone authenticates.
 *   method: Matomo API method.
 *   params: its parameters.
 */
async function apiSuccess(request, method, params) {
  const answer = await matomoApi(request, method, params);
  expect(answer?.result, `${method} must succeed: ${answer?.message}`).not.toBe("error");
}

/**
 * Args:
 *   request: the request fixture.
 *   probe: the probeAccount() to create with view access to site 1 and no second factor.
 */
async function createProbe(request, probe) {
  await apiSuccess(request, "UsersManager.addUser", {
    userLogin: probe.login,
    password: probe.password,
    email: `${probe.login}@${canonicalDomain}`,
  });
  await apiSuccess(request, "UsersManager.setUserAccess", { userLogin: probe.login, access: "view", idSites: "1" });
}

/**
 * Args:
 *   request: the request fixture.
 *   probe: the probeAccount() to delete.
 */
async function deleteProbe(request, probe) {
  await matomoApi(request, "UsersManager.deleteUser", { userLogin: probe.login }).catch((error) =>
    console.warn(`deleting the probe account failed: ${error}`),
  );
}

/**
 * Args:
 *   page: signed-in page; ends on the reports, or on what Matomo serves in their place.
 *
 * Returns:
 *   The HTML Matomo answered the reports URL with.
 */
async function openReports(page) {
  const response = await gotoOnion(page, REPORTS);
  expect(response, "the reports URL must answer").toBeTruthy();
  return response.text();
}

test("2fa enrollment: with its own second factor enforced Matomo sends a local account without one to setup and lets it in once enrolled", async ({ page, request }) => {
  test.skip(!nativeLoginEnabled, "LOGIN_METHOD_NATIVE_ENABLED=false");
  test.skip(!twoFactorEnforced, "LOGIN_METHOD_2FA_ENFORCED=false");
  test.setTimeout(resolveTimeout(300_000));

  await seedVisits(request);
  const probe = probeAccount();
  try {
    await createProbe(request, probe);
    await signIn(page, probe.login, probe.password);
    await expect(page.locator(SETUP), "the sign-in must end on the 2FA setup").toBeVisible({ timeout: resolveTimeout(60_000) });

    const html = await openReports(page);
    expect(html, "the reports must serve the standalone setup instead").toContain(STANDALONE_SETUP);
    await expect(page.locator(SETUP), "the reports must hand the account back to the 2FA setup").toBeVisible({
      timeout: resolveTimeout(60_000),
    });
    await expect(page.locator(MENU), "the reporting menu must stay out of reach").toHaveCount(0);

    const secret = html.match(SECRET)?.[1];
    const nonce = html.match(NONCE)?.[1];
    expect(secret, "the setup must carry the new TOTP secret").toBeTruthy();
    expect(nonce, "the setup must carry its form nonce").toBeTruthy();
    const confirmed = await page.request.post(CONFIRM, {
      form: { authCode: totpCode(secret), authCodeNonce: nonce },
      timeout: resolveTimeout(30_000),
    });
    expect(confirmed.status(), "confirming the TOTP code must be answered").toBeLessThan(400);

    expect(await openReports(page), "once enrolled the account must get the reports").not.toContain(STANDALONE_SETUP);
    await expect(page.locator(MENU).first(), "once enrolled the account must reach the reporting menu").toBeVisible({
      timeout: resolveTimeout(60_000),
    });
  } finally {
    await deleteProbe(request, probe);
  }
});

test("2fa enrollment: the enforced second factor sends the Matomo administrator to setup as well", async ({ page }) => {
  test.skip(!nativeLoginEnabled, "LOGIN_METHOD_NATIVE_ENABLED=false");
  test.skip(!twoFactorEnforced, "LOGIN_METHOD_2FA_ENFORCED=false");

  await signIn(page, adminUsername, adminPassword);
  await expect(page.locator(SETUP), "the administrator's sign-in must end on the 2FA setup").toBeVisible({
    timeout: resolveTimeout(60_000),
  });
  expect(await openReports(page), "the reports must serve the administrator the standalone setup").toContain(STANDALONE_SETUP);
  await expect(page.locator(MENU), "the reporting menu must stay out of the administrator's reach").toHaveCount(0);
});

test("2fa enrollment: with the enforcement off Matomo lets a local account without a second factor straight in", async ({ page, request }) => {
  test.skip(!nativeLoginEnabled, "LOGIN_METHOD_NATIVE_ENABLED=false");
  test.skip(twoFactorEnforced, "LOGIN_METHOD_2FA_ENFORCED=true");
  test.setTimeout(resolveTimeout(300_000));

  await seedVisits(request);
  const probe = probeAccount();
  try {
    await createProbe(request, probe);
    await signIn(page, probe.login, probe.password);
    expect(await openReports(page), "without the enforcement the reports must not serve the setup").not.toContain(STANDALONE_SETUP);
    await expect(page.locator(MENU).first(), "without the enforcement the account must reach the reporting menu").toBeVisible({
      timeout: resolveTimeout(60_000),
    });
  } finally {
    await deleteProbe(request, probe);
  }
});
