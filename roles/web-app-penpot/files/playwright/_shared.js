// Shared state + login helpers for the Penpot Playwright suite.
// playwright.spec.js wires the lifecycle hook and `require()`s one test-*.js
// companion per login surface (native / oidc / ldap), passing this module as
// `shared` so each scenario stays atomar and individually inspectable.

const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled, isServiceEnabled } = require("./service-gating");
const {
  decodeDotenvQuotedValue,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
} = require("./personas");

const env = {
  baseUrl: normalizeBaseUrl(process.env.PENPOT_BASE_URL || ""),
  oidcIssuerUrl: normalizeBaseUrl(process.env.OIDC_ISSUER_URL || ""),
  canonicalDomain: decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || ""),
  adminUsername: decodeDotenvQuotedValue(process.env.ADMIN_USERNAME),
  adminPassword: decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD),
  adminEmail: decodeDotenvQuotedValue(process.env.ADMIN_EMAIL),
  biberUsername: decodeDotenvQuotedValue(process.env.BIBER_USERNAME),
  biberPassword: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD),
  biberEmail: decodeDotenvQuotedValue(process.env.BIBER_EMAIL),
};

const loginRoute = (base) => `${base.replace(/\/$/, "")}/#/auth/login`;

async function assertAuthenticated(page) {
  // Leaving /auth/login proves a real session (dashboard/onboarding renders).
  await expect
    .poll(() => page.url(), { timeout: 60_000, message: "expected to leave the login route after sign-in" })
    .not.toContain("/auth/login");
  await expect(page.locator("body")).toBeVisible({ timeout: 60_000 });
}

// In-app OIDC (flavor: oidc): the login page renders an "OpenID" provider entry
// (clickable text, not a role=button) that redirects to Keycloak.
async function penpotOidcLogin(page, username, password) {
  const expectedAuth = `${env.oidcIssuerUrl}/protocol/openid-connect/auth`;
  await page.goto(loginRoute(env.baseUrl));
  const oidcEntry = page.getByText("OpenID", { exact: true });
  await expect(oidcEntry, "Expected a Penpot OpenID login entry").toBeVisible({ timeout: 60_000 });
  await oidcEntry.click();
  await expect
    .poll(() => page.url(), { timeout: 60_000, message: `expected redirect to ${expectedAuth}` })
    .toContain(expectedAuth);
  await performKeycloakLoginForm(page, username, password);
  await assertAuthenticated(page);
}

// LDAP: a dedicated "LDAP" submit button (enabled once the form is filled)
// binds against OpenLDAP directly — no Keycloak round-trip.
async function penpotLdapLogin(page, email, password) {
  await page.goto(loginRoute(env.baseUrl));
  const emailField = page.getByLabel(/work email/i);
  const passwordField = page.getByLabel(/^password$/i);
  await expect(emailField, "Expected the Penpot login form").toBeVisible({ timeout: 60_000 });
  await emailField.fill(email);
  await passwordField.fill(password);
  const ldapButton = page.getByRole("button", { name: /^LDAP$/i });
  await expect(ldapButton, "Expected the LDAP submit button to enable once the form is filled").toBeEnabled({ timeout: 30_000 });
  await ldapButton.click();
  await assertAuthenticated(page);
}

// Native: register a fresh local-DB account (Penpot's register flow can be a
// two-step form: email/password, then full name). SMTP-off deployments activate
// the profile immediately (no verification), landing on the dashboard.
async function penpotRegister(page, fullname, email, password) {
  await page.goto(`${env.baseUrl.replace(/\/$/, "")}/#/auth/register`);
  const emailField = page.getByLabel(/work email|^email$/i).first();
  const passwordField = page.getByLabel(/^password$/i).first();
  await expect(emailField, "Expected the Penpot register form").toBeVisible({ timeout: 60_000 });
  await emailField.fill(email);
  await passwordField.fill(password);
  const next = page.getByRole("button", { name: /create an account|create account|sign up|register|next|continue/i }).first();
  await expect(next, "Expected the register submit button to enable").toBeEnabled({ timeout: 30_000 });
  await next.click();

  // Optional second step: full name + terms acceptance.
  const nameField = page.getByLabel(/full ?name|^name$/i).first();
  if (await nameField.isVisible({ timeout: 15_000 }).catch(() => false)) {
    await nameField.fill(fullname);
    const terms = page.getByRole("checkbox").first();
    if (await terms.isVisible().catch(() => false)) await terms.check().catch(() => {});
    const finish = page.getByRole("button", { name: /create an account|create account|sign up|register|next|continue|finish/i }).first();
    await expect(finish).toBeEnabled({ timeout: 30_000 });
    await finish.click();
  }
  await assertAuthenticated(page);
}

// Native: local-DB account via the email/password form + the "Login" button.
async function penpotNativeLogin(page, email, password) {
  await page.goto(loginRoute(env.baseUrl));
  const emailField = page.getByLabel(/work email/i);
  const passwordField = page.getByLabel(/^password$/i);
  await expect(emailField, "Expected the Penpot login form").toBeVisible({ timeout: 60_000 });
  await emailField.fill(email);
  await passwordField.fill(password);
  const loginButton = page.getByRole("button", { name: /^Login$/i });
  await expect(loginButton, "Expected the Login button to enable once the form is filled").toBeEnabled({ timeout: 30_000 });
  await loginButton.click();
  await assertAuthenticated(page);
}

module.exports = {
  test,
  expect,
  skipUnlessServiceEnabled,
  isServiceEnabled,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
  env,
  loginRoute,
  penpotOidcLogin,
  penpotLdapLogin,
  penpotNativeLogin,
  penpotRegister,
};
