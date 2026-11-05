const { expect } = require("@playwright/test");
const {
  decodeDotenvQuotedValue,
  gotoOnion,
  installCspViolationObserver,
  normalizeBaseUrl,
  performKeycloakLogin,
  readEnv,
  runAdminFlow,
  runGuestFlow,
} = require("./personas");
const { isServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const USER_MENU = ".usermenu, [data-region='user-menu-toggle'], a[href*='profile.php']";

const env = {
  moodleBaseUrl: normalizeBaseUrl(process.env.APP_BASE_URL),
  oidcIssuerUrl: normalizeBaseUrl(process.env.OIDC_ISSUER_URL || ""),
  oidcClientId: decodeDotenvQuotedValue(process.env.OIDC_CLIENT_ID || ""),
  adminUsername: decodeDotenvQuotedValue(process.env.ADMIN_USERNAME),
  adminPassword: decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD),
  adminNativePassword: decodeDotenvQuotedValue(process.env.ADMIN_NATIVE_PASSWORD || ""),
  biberUsername: decodeDotenvQuotedValue(process.env.BIBER_USERNAME),
  biberPassword: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD),
  ssoEnabled: isServiceEnabled("sso"),
  ldapEnabled: isServiceEnabled("ldap"),
};

/**
 * Open an authenticated site-administrator session.
 *
 * @param {import('@playwright/test').Page} page browser page to authenticate
 */
async function loginAsSiteAdmin(page) {
  if (env.ssoEnabled) {
    await gotoOnion(page, `${env.moodleBaseUrl}/auth/oidc/?source=loginpage`, {
      waitUntil: "domcontentloaded",
      timeout: resolveTimeout(60_000),
    });
    await performKeycloakLogin(
      page,
      env.adminUsername,
      env.adminPassword,
      readEnv("CANONICAL_DOMAIN"),
    );
  } else {
    expect(
      env.adminNativePassword,
      "ADMIN_NATIVE_PASSWORD must be rendered from the administrator user; with the sso service off it is the only secret that authenticates the Moodle site administrator",
    ).toBeTruthy();

    await gotoOnion(page, `${env.moodleBaseUrl}/login/index.php`, {
      waitUntil: "domcontentloaded",
      timeout: resolveTimeout(60_000),
    });
    await page
      .locator("input[name='username'], input#username")
      .first()
      .fill(env.adminUsername);

    const passwordInput = page
      .locator(
        ".toggle-sensitive-wrapper input[name='password'], .toggle-sensitive-wrapper input#password, input[name='password']",
      )
      .first();
    await expect(
      passwordInput,
      "the native Moodle login form must expose a password field; its absence means the login page no longer serves the manual auth form",
    ).toBeAttached({ timeout: resolveTimeout(30_000) });
    await expect(async () => {
      await passwordInput.fill(env.adminNativePassword);
      await expect(passwordInput).toHaveValue(env.adminNativePassword);
    }).toPass({ timeout: resolveTimeout(30_000) });

    await page.locator("#loginbtn, button[type='submit'], input[type='submit']").first().click();
    await page.waitForLoadState("load");
  }

  await expect(
    page.locator(USER_MENU).first(),
    "the site administrator must reach an authenticated session; a failure here means the auth chain the deploy configured does not admit the administrator account",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
}

async function beforeEach({ page }) {
  await page.setViewportSize({ width: 1440, height: 1100 });
  expect(env.moodleBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(env.adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(env.adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
  expect(env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
  expect(env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();
  await page.context().clearCookies();
  await installCspViolationObserver(page);
}

const setMiddleNameViaAccountRest = async ({
  issuer,
  clientId,
  username,
  password,
  middleName,
  withRestore,
}) => {
  const tokenForm = new URLSearchParams({
    grant_type: "password",
    client_id: clientId,
    username,
    password,
    scope: "openid",
  });
  const tokenResp = await fetch(`${issuer}/protocol/openid-connect/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded", accept: "application/json" },
    body: tokenForm.toString(),
  });
  const tokenBody = await tokenResp.text();
  if (!tokenResp.ok) return { stage: "token", status: tokenResp.status, body: tokenBody };
  const accessToken = JSON.parse(tokenBody).access_token;
  const auth = { authorization: `Bearer ${accessToken}`, accept: "application/json" };

  const metaResp = await fetch(`${issuer}/account/?userProfileMetadata=true`, { headers: auth });
  const metaBody = await metaResp.text();
  if (!metaResp.ok) return { stage: "meta", status: metaResp.status, body: metaBody };
  const meta = JSON.parse(metaBody);

  const original = (meta.attributes && meta.attributes.middleName)
    ? meta.attributes.middleName
    : null;
  const update = {
    ...meta,
    attributes: { ...(meta.attributes || {}), middleName: [middleName] },
  };
  delete update.userProfileMetadata;

  const upResp = await fetch(`${issuer}/account/`, {
    method: "POST",
    headers: { ...auth, "content-type": "application/json" },
    body: JSON.stringify(update),
  });
  const upBody = await upResp.text();
  if (!upResp.ok) return { stage: "update", status: upResp.status, body: upBody };

  const attrNames = (meta.userProfileMetadata?.attributes || []).map((a) => a.name);

  if (!withRestore) {
    return { stage: "ok", attrNames, original };
  }

  const verifyResp = await fetch(`${issuer}/account/`, { headers: auth });
  const verifyBody = await verifyResp.text();
  if (!verifyResp.ok) return { stage: "verify", status: verifyResp.status, body: verifyBody };
  const verified = JSON.parse(verifyBody);

  const restoreAttrs = { ...(verified.attributes || {}) };
  if (original) {
    restoreAttrs.middleName = original;
  } else {
    delete restoreAttrs.middleName;
  }
  const restore = { ...verified, attributes: restoreAttrs };
  delete restore.userProfileMetadata;
  await fetch(`${issuer}/account/`, {
    method: "POST",
    headers: { ...auth, "content-type": "application/json" },
    body: JSON.stringify(restore),
  });

  return {
    stage: "ok",
    attrNames,
    verifiedMiddleName: verified.attributes?.middleName?.[0],
  };
};

module.exports = {
  env,
  beforeEach,
  loginAsSiteAdmin,
  runAdminFlow,
  runGuestFlow,
  setMiddleNameViaAccountRest,
};
