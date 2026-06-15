// End-to-end smoke tests for the OpenTalk role.
//
// Two scenarios mirroring the nextcloud convention:
//   1. administrator persona — SSO login lands on the OpenTalk dashboard.
//   2. biber persona — same flow in an isolated browser context.
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

function attachDiagnostics(page) {
  const d = { console: [], errors: [], requests: [] };
  page.on("console", (msg) => d.console.push(`[${msg.type()}] ${msg.text()}`));
  page.on("pageerror", (err) => d.errors.push(String(err)));
  page.on("response", (resp) => {
    if (!resp.ok() && resp.status() >= 400) {
      d.requests.push(`${resp.status()} ${resp.request().method()} ${resp.url()}`);
    }
  });
  return d;
}

async function ssoLoginAndAssertDashboard(page, username, password) {
  const diagnostics = attachDiagnostics(page);
  await page.goto(baseUrl);

  // The OpenTalk frontend either auto-redirects to Keycloak or renders a
  // "Sign in" CTA first. Race both paths.
  if (!issuerPattern.test(page.url())) {
    const signInCta = page.getByRole("button", { name: /sign in|log in|anmelden/i });
    if (await signInCta.first().isVisible({ timeout: 10_000 }).catch(() => false)) {
      await signInCta.first().click();
    }
    await page.waitForURL(issuerPattern, { timeout: 60_000 });
  }

  await page.locator('input[name="username"], #username').fill(username);
  await page.locator('input[name="password"], #password').fill(password);
  // Submit via Enter to avoid Playwright's post-click stability wait that
  // races with the multi-step OIDC redirect chain back to OpenTalk.
  await page.locator('input[name="password"], #password').press("Enter");

  await page.waitForURL(baseUrlPattern, { timeout: 60_000 });
  // The dashboard renders a left-side navigation list with a Home link plus
  // a profile link that contains the LDAP user's full display name. Use
  // the Home link as the proof of a fully-loaded authenticated dashboard.
  try {
    await expect(page.getByRole("link", { name: /^home$/i }).first()).toBeVisible({
      timeout: 60_000,
    });
  } catch (err) {
    const summary = [
      `URL when stuck: ${page.url()}`,
      `Console (${diagnostics.console.length}):`,
      ...diagnostics.console.slice(-25),
      `Errors (${diagnostics.errors.length}):`,
      ...diagnostics.errors.slice(-10),
      `Failed responses (${diagnostics.requests.length}):`,
      ...diagnostics.requests.slice(-15),
    ].join("\n");
    throw new Error(`OpenTalk dashboard never appeared.\n${summary}\nOriginal: ${err}`, { cause: err });
  }
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
  ssoLoginAndAssertDashboard,
};
