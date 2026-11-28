// Shared Gitea Playwright spec state: env vars, persona helpers and the
// `beforeEach` env-presence guard. `playwright.spec.js` wires the lifecycle
// hook and `require()`s one test module per scenario so each test stays
// atomar and individually inspectable.

const { expect } = require("@playwright/test");

const {
  decodeDotenvQuotedValue,
  gotoOnion,
  performKeycloakLogin,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
} = require("./personas");
const { isServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

// `docker --env-file` preserves the quotes emitted by `dotenv_quote`,
// so normalize these values before building URLs or typing credentials.
const gitEaBaseUrl = decodeDotenvQuotedValue(process.env.GITEA_BASE_URL);
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);

const loginMethods = {
  ldap: process.env.LOGIN_METHOD_LDAP_ENABLED === "true",
  native: process.env.LOGIN_METHOD_NATIVE_ENABLED === "true",
  openid2: process.env.LOGIN_METHOD_OPENID2_ENABLED === "true",
  passkey: process.env.LOGIN_METHOD_PASSKEY_ENABLED === "true",
  registration: process.env.LOGIN_METHOD_REGISTRATION_ENABLED === "true",
};

const twoFactorEnforced = process.env.LOGIN_METHOD_2FA_ENFORCED === "true";

function passwordFormEnabled() {
  return loginMethods.native || loginMethods.ldap;
}

async function signIn(page, username, password) {
  const base = gitEaBaseUrl.replace(/\/$/, "");
  await gotoOnion(page, `${base}/user/login`);
  if (isServiceEnabled("sso") && (await page.locator("#kc-form-login").isVisible())) {
    await performKeycloakLogin(page, username, password, canonicalDomain);
  }
  if (passwordFormEnabled()) {
    await gotoOnion(page, `${base}/user/login`);
    await expect(page.locator("#user_name")).toBeEditable({ timeout: resolveTimeout(30_000) });
    await page.locator("#user_name").fill(username);
    await expect(page.locator("#password")).toBeEditable({ timeout: resolveTimeout(30_000) });
    await page.locator("#password").fill(password);
    await page.locator("#password").press("Enter");
  }
  await expect(
    page.locator("#navbar [data-signed-in-username]"),
    `${username} must end signed in to Gitea`,
  ).toHaveAttribute("data-signed-in-username", username, { timeout: resolveTimeout(60_000) });
}

function healthzReadyUrl() {
  return `${gitEaBaseUrl.replace(/\/$/, "")}/healthz/ready`;
}

function mcpEndpointUrl() {
  return `${gitEaBaseUrl.replace(/\/$/, "")}/mcp`;
}

function beforeEach() {
  expect(gitEaBaseUrl, "GITEA_BASE_URL must be set in the Playwright env file").toBeTruthy();
}

module.exports = {
  env: { gitEaBaseUrl },
  healthzReadyUrl,
  loginMethods,
  mcpEndpointUrl,
  signIn,
  twoFactorEnforced,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
  beforeEach,
};
