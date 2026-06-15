const { expect } = require("@playwright/test");

const { decodeDotenvQuotedValue } = require("./personas");

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

async function ssoLoginAndAssertUsername(page, username, password) {
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
  await page.goto(baseUrl);

  const onIssuer = async () => issuerPattern.test(page.url());
  if (!(await onIssuer())) {
    // Either click the Login control on the OpenCloud SPA or wait for the
    // SPA to redirect to Keycloak. Try both in parallel and finish on
    // whichever happens first.
    const loginCta = page.locator(
      'button:has-text("Login"), button:has-text("Sign in"), button:has-text("Log in"), [data-test-id="login-button"], a[href*="oidc"]'
    );
    try {
      await Promise.race([
        page.waitForURL(issuerPattern, { timeout: 60_000 }),
        (async () => {
          await loginCta.first().waitFor({ state: "visible", timeout: 60_000 });
          await Promise.all([
            page.waitForURL(issuerPattern, { timeout: 60_000 }),
            loginCta.first().click(),
          ]);
        })(),
      ]);
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

  await page.locator('input[name="username"], #username').fill(username);
  await page.locator('input[name="password"], #password').fill(password);
  const leftKeycloak = page
    .waitForURL((url) => !issuerPattern.test(url.toString()), { timeout: 60_000 })
    .catch(() => {});
  await page
    .locator('input[name="password"], #password')
    .press("Enter", { timeout: 5_000 })
    .catch(() => {});
  await leftKeycloak;

  // Fast-fail on a Keycloak credential rejection: the form re-renders with
  // `#input-error` / `.alert-error` instead of redirecting to the callback,
  // and the 90s banner wait below would otherwise bury the real cause.
  const credentialError = page
    .locator('#input-error, .alert-error, .kc-feedback-text')
    .first();
  if (await credentialError.isVisible({ timeout: 5_000 }).catch(() => false)) {
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
    await page.waitForURL(baseUrlPattern, { timeout: 60_000, waitUntil: "load" });
  } catch {
    // SPA may have already navigated past the matcher window; fall
    // through to the visibility assertions which carry their own waits.
  }

  // Bypass OpenCloud's "browser not supported" splash if it appears.
  // Playwright's Chromium UA is not on the OpenCloud allow list, so the SPA
  // shows a splash with a "I want to continue anyway" button.
  const continueAnyway = page.getByRole("button", { name: /continue anyway/i });
  if (await continueAnyway.isVisible({ timeout: 5_000 }).catch(() => false)) {
    await continueAnyway.click();
  }

  // The Files view is the post-login landing route; assert against the SPA
  // navigation banner instead of body text because OpenCloud shows the
  // username inside the user-menu drawer rather than in the page body.
  await expect(page.getByRole("banner", { name: /top bar/i })).toBeVisible({ timeout: 90_000 });
  await expect(page.getByRole("link", { name: /personal files/i })).toBeVisible({ timeout: 30_000 });
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
  ssoLoginAndAssertUsername,
};
