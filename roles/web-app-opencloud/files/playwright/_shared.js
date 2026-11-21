const { expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { decodeDotenvQuotedValue, gotoOnion } = require("./personas");

const baseUrl = decodeDotenvQuotedValue(process.env.APP_BASE_URL);
const issuerUrl = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL);
const adminUsername = decodeDotenvQuotedValue(process.env.LOGIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.LOGIN_PASSWORD);
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);

const issuerHost = new URL(issuerUrl).host;
const issuerPattern = new RegExp(`^https?://${issuerHost.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`);
const baseUrlPattern = new RegExp(`^${baseUrl.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`);

function attachDiagnostics(page, _label) {
  const diagnostics = { console: [], requests: [], errors: [] };
  page.on("console", (msg) => {
    diagnostics.console.push(`[${msg.type()}] ${msg.text()}`);
  });
  page.on("pageerror", (err) => {
    diagnostics.errors.push(String(err));
  });
  page.on("requestfailed", (req) => {
    diagnostics.requests.push(`${req.failure()?.errorText || ""} ${req.method()} ${req.url()}`);
  });
  return diagnostics;
}

async function ssoLogin(page, username, password) {
  const diagnostics = attachDiagnostics(page, username);
  // OpenCloud Web's index.html shows a "browser not supported" splash unless
  // `forceAllowOldBrowser` is present in localStorage. Playwright's headless
  // Chromium UA is not on its allow list, so prime the flag for the host
  // before any navigation happens.
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem(
        "forceAllowOldBrowser",
        JSON.stringify({ expiry: Date.now() + 30 * 24 * 60 * 60 * 1000 })
      );
    } catch {}
  });
  await gotoOnion(page, baseUrl);

  const onIssuer = async () => issuerPattern.test(page.url());
  if (!(await onIssuer())) {
    const loginCta = page.locator(
      'button:has-text("Login"), button:has-text("Sign in"), button:has-text("Log in"), [data-test-id="login-button"], a[href*="oidc"]'
    );
    const reachedIssuer = page
      .waitForURL(issuerPattern, { timeout: resolveTimeout(60_000) })
      .then(() => true)
      .catch(() => false);
    const ctaReady = loginCta
      .first()
      .waitFor({ state: "visible", timeout: resolveTimeout(60_000) })
      .then(() => true)
      .catch(() => false);
    try {
      await Promise.race([reachedIssuer, ctaReady]);
      if (!(await onIssuer()) && (await ctaReady)) {
        await loginCta.first().click({ timeout: resolveTimeout(30_000) });
      }
      if (!(await reachedIssuer)) {
        throw new Error("the SPA neither redirected to Keycloak nor offered a Login control that did");
      }
    } catch (err) {
      const summary = [
        `URL when stuck: ${page.url()}`,
        `Console (${diagnostics.console.length}):`,
        ...diagnostics.console.slice(-25),
        `Page errors (${diagnostics.errors.length}):`,
        ...diagnostics.errors.slice(-10),
        `Failed requests (${diagnostics.requests.length}):`,
        ...diagnostics.requests.slice(-10),
      ].join("\n");
      throw new Error(`OpenCloud SPA never reached Keycloak.\n${summary}\nOriginal error: ${err}`, { cause: err });
    }
  }

  const usernameField = page.locator('input[name="username"], #username');
  const passwordField = page.locator('input[name="password"], #password');
  await usernameField.fill(username);
  await passwordField.fill(password);

  await expect
    .poll(
      async () =>
        (await usernameField.inputValue()) === username &&
        (await passwordField.inputValue()) === password,
      {
        timeout: resolveTimeout(10_000),
        message: "Expected the Keycloak login form to still carry both credentials at submit time",
      },
    )
    .toBe(true);

  const leftKeycloak = page
    .waitForURL((url) => !issuerPattern.test(url.toString()), { timeout: resolveTimeout(60_000) })
    .catch(() => {});
  await page
    .locator('#kc-login, input[type="submit"], button[type="submit"]')
    .first()
    .click({ timeout: resolveTimeout(30_000) })
    .catch(() => {});
  await leftKeycloak;

  // Fast-fail on a Keycloak credential rejection: the form re-renders with
  // `#input-error` / `.alert-error` instead of redirecting to the callback,
  // and the 90s banner wait below would otherwise bury the real cause.
  const credentialError = page
    .locator('#input-error, .alert-error, .kc-feedback-text')
    .first();
  if (await credentialError.isVisible().catch(() => false)) {
    const message = ((await credentialError.textContent().catch(() => "")) || "").trim();
    throw new Error(
      `Keycloak rejected credentials for ${username}: "${message || "<no message>"}" (final URL: ${page.url()})`,
    );
  }

  // Wait for the redirect chain back to OpenCloud to finish before
  // asserting on SPA elements. Without this the banner assertion races
  // the OIDC callback hops (auth → /oidc-callback → /web-oidc-callback →
  // SPA) and times out before the Files view actually mounts.
  try {
    await page.waitForURL(baseUrlPattern, { timeout: resolveTimeout(60_000), waitUntil: "load" });
  } catch {
    // SPA may have already navigated past the matcher window; fall
    // through to the visibility assertions which carry their own waits.
  }

  // Bypass OpenCloud's "browser not supported" splash if it appears.
  // Playwright's Chromium UA is not on the OpenCloud allow list, so the SPA
  // shows a splash with a "I want to continue anyway" button.
  const continueAnyway = page.getByRole("button", { name: /continue anyway/i });
  if (await continueAnyway.waitFor({ state: "visible", timeout: resolveTimeout(2_000) }).then(() => true).catch(() => false)) {
    await continueAnyway.click();
  }

  // The Files view is the post-login landing route; assert against the SPA
  // navigation banner instead of body text because OpenCloud shows the
  // username inside the user-menu drawer rather than in the page body.
  await expect(page.getByRole("banner", { name: /top bar/i })).toBeVisible({ timeout: resolveTimeout(90_000) });
}

async function ssoLoginAndAssertUsername(page, username, password) {
  await ssoLogin(page, username, password);
  await expect(page.getByRole("link", { name: /personal files/i })).toBeVisible({ timeout: resolveTimeout(30_000) });
}

async function logoutThroughAccountMenu(page) {
  await page.locator("#_userMenuButton").click({ timeout: resolveTimeout(30_000) });
  await page.locator("#account-info-container #oc-topbar-account-logout").click({ timeout: resolveTimeout(30_000) });
  await expect(page.locator("#_userMenuButton"), "the top bar account button must disappear after logout").toBeHidden({
    timeout: resolveTimeout(60_000),
  });
}

async function ownRoleIds(page) {
  const result = await page.evaluate(async () => {
    let token = "";
    for (const store of [window.sessionStorage, window.localStorage]) {
      for (let index = 0; index < store.length; index += 1) {
        try {
          const value = JSON.parse(store.getItem(store.key(index)) || "null");
          if (value && typeof value.access_token === "string") {
            token = value.access_token;
          }
        } catch {}
      }
    }
    if (!token) {
      return { error: "no access token in the browser storage" };
    }
    const headers = { Authorization: `Bearer ${token}` };
    const me = await fetch("/graph/v1.0/me", { headers });
    if (!me.ok) {
      return { error: `GET /graph/v1.0/me answered ${me.status}` };
    }
    const { id } = await me.json();
    const assignments = await fetch("/api/v0/settings/assignments-list", {
      method: "POST",
      headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify({ account_uuid: id }),
    });
    if (!assignments.ok) {
      return { error: `POST /api/v0/settings/assignments-list answered ${assignments.status}` };
    }
    const body = await assignments.json();
    return { roleIds: (body.assignments || []).map((assignment) => assignment.roleId).filter(Boolean) };
  });
  expect(result.error, `the OpenCloud role probe failed: ${result.error}`).toBeUndefined();
  return result.roleIds;
}

module.exports = {
  baseUrl,
  issuerUrl,
  adminUsername,
  adminPassword,
  biberUsername,
  biberPassword,
  issuerHost,
  issuerPattern,
  baseUrlPattern,
  attachDiagnostics,
  ssoLogin,
  ssoLoginAndAssertUsername,
  logoutThroughAccountMenu,
  ownRoleIds,
};
