const { expect } = require("@playwright/test");

const {
  decodeDotenvQuotedValue,
  gotoOnion,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  requireDotenvValue,
} = require("./personas");
const { isServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const FORM_MS = 10_000;

function env(name) {
  return decodeDotenvQuotedValue(process.env[name]);
}

function baseUrl() {
  return normalizeBaseUrl(env("DISCOURSE_BASE_URL"));
}

async function signInViaOidc(page, base) {
  const issuer = normalizeBaseUrl(requireDotenvValue(process.env.OIDC_ISSUER_URL, "OIDC_ISSUER_URL"));
  await gotoOnion(page, `${base}/`);
  await page
    .locator("a, button")
    .filter({ hasText: /log\s*in|sign\s*in/i })
    .first()
    .click({ timeout: resolveTimeout(30_000) });
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `expected redirect to Keycloak OIDC auth (${issuer})`,
    })
    .toContain(`${issuer}/protocol/openid-connect/auth`);
  await performKeycloakLoginForm(page, env("ADMIN_USERNAME"), env("ADMIN_PASSWORD"));
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `expected redirect back to discourse at ${base}`,
    })
    .toContain(base);
  await gotoOnion(page, `${base}/latest`);
}

async function signInViaLocalLogin(page, base) {
  await gotoOnion(page, `${base}/login`);
  const name = page.locator("#login-account-name");
  const password = page.locator("#login-account-password");
  await expect(name, `expected the local login form at ${base}/login (enable_local_logins follows services.sso.enabled)`).toBeEditable({
    timeout: resolveTimeout(FORM_MS),
  });
  await name.fill(env("ADMIN_USERNAME"));
  await expect(password).toBeEditable({ timeout: resolveTimeout(FORM_MS) });
  await password.fill(env("ADMIN_PASSWORD"));
  await password.press("Enter");
}

async function signInAsAdmin(page) {
  const base = baseUrl();
  if (isServiceEnabled("sso")) {
    await signInViaOidc(page, base);
  } else {
    await signInViaLocalLogin(page, base);
  }
  await expect(
    page.locator(".header-dropdown-toggle.current-user"),
    "expected discourse to answer with the signed-in administrator's own user menu",
  ).toBeVisible({ timeout: resolveTimeout(30_000) });
}

module.exports = { signInAsAdmin };
