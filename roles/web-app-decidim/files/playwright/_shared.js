const { expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvQuotedValue, gotoOnion, performKeycloakLoginForm, requireDotenvValue } = require("./personas");

const baseUrl = decodeDotenvQuotedValue(process.env.DECIDIM_BASE_URL || process.env.APP_BASE_URL);
const oidcIssuerUrl = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL);

const env = {
  loginMethodNative: process.env.LOGIN_METHOD_NATIVE_ENABLED === "true",
  loginMethodRegistration: process.env.LOGIN_METHOD_REGISTRATION_ENABLED === "true",
  loginMethodSso: process.env.LOGIN_METHOD_SSO_ENABLED === "true",
};

const SSO_ENTRY = "a[href*='openid_connect']";

/**
 * Args:
 *   page: Playwright page whose cookie consent banner is accepted when it shows; Decidim's overlay otherwise steals the pointer events of form buttons.
 */
async function dismissCookieBanner(page) {
  const acceptBtn = page.getByRole("button", { name: /accept all|accept only essential|accept/i }).first();
  if (await acceptBtn.isVisible().catch(() => false)) {
    await acceptBtn.click().catch(() => {});
    await page.waitForLoadState("networkidle", { timeout: resolveTimeout(5000) }).catch(() => {});
  }
}

/**
 * Returns: the administrator's Keycloak login id. Under the mailbox email policy Keycloak resolves an e-mail login against the secondary address, so the mailbox in ADMIN_EMAIL signs nobody in; its local part is the username.
 */
function adminKeycloakLoginId() {
  const adminEmail = requireDotenvValue(process.env.ADMIN_EMAIL, "ADMIN_EMAIL");
  return requireDotenvValue(process.env.KEYCLOAK_EMAIL_POLICY, "KEYCLOAK_EMAIL_POLICY") === "mailbox"
    ? adminEmail.split("@")[0]
    : adminEmail;
}

/**
 * Args:
 *   page: Playwright page that ends signed in to Decidim through Keycloak.
 *   username: Keycloak username or e-mail address.
 *   password: Keycloak password.
 */
async function oidcLogin(page, username, password) {
  await gotoOnion(page, `${baseUrl}/users/sign_in`);
  await page.waitForLoadState("networkidle");
  await dismissCookieBanner(page);
  const ssoButton = page.locator(SSO_ENTRY).first();
  await expect(
    ssoButton,
    "Expected the Decidim OpenID Connect sign-in button while the sso service is enabled",
  ).toBeVisible({ timeout: resolveTimeout(30_000) });
  const ssoHref = await ssoButton.getAttribute("href");
  console.log("SSO href:", ssoHref);
  await page.waitForFunction(() => document.readyState === "complete");
  const oidcAuthHost = new URL(oidcIssuerUrl).host;
  const navigated = page.waitForURL((url) => url.host === oidcAuthHost, { timeout: resolveTimeout(30000) });
  await page.evaluate((href) => {
    const csrfToken = document.querySelector("meta[name='csrf-token']")?.getAttribute("content") || "";
    const form = document.createElement("form");
    form.setAttribute("method", "post");
    form.setAttribute("action", href);
    const token = document.createElement("input");
    token.setAttribute("type", "hidden");
    token.setAttribute("name", "authenticity_token");
    token.setAttribute("value", csrfToken);
    form.appendChild(token);
    document.body.appendChild(form);
    form.submit();
  }, ssoHref);
  await navigated.catch(e => console.log("nav error:", e.message, "url:", page.url()));
  console.log("After form submit URL:", page.url());
  await performKeycloakLoginForm(page, username, password);
  console.log("Login clicked, waiting for redirect back...");
  await page.waitForLoadState("networkidle", { timeout: resolveTimeout(30000) }).catch(e => console.log("networkidle error:", e.message));
  console.log("After login URL:", page.url());
  await dismissCookieBanner(page);

  const tosCheckbox = page.locator("input[type='checkbox'][name='user[tos_agreement]']").first();
  const onRegistrationForm = await tosCheckbox.isVisible().catch(() => false);
  if (onRegistrationForm) {
    console.log("First-time OIDC registration form detected, accepting TOS...");
    await tosCheckbox.check({ force: true });
    // The user-registration-form Stimulus controller cancels the submit and opens a newsletter modal while user[newsletter] is unchecked.
    await page.evaluate(() => document.getElementById("omniauth-register-form").requestSubmit());
    const declineBtn = page.locator("#sign-up-newsletter-modal [data-check='false']").first();
    await declineBtn.waitFor({ state: "visible", timeout: resolveTimeout(10000) });
    await Promise.all([
      page.waitForURL((url) => !/auth\/openid_connect\/callback/.test(url.toString()), { timeout: resolveTimeout(30000) }).catch(e => console.log("post-submit nav error:", e.message)),
      declineBtn.click({ force: true, timeout: resolveTimeout(30_000) }),
    ]);
    console.log("After registration URL:", page.url());
    await page.waitForURL((url) => url.host === new URL(baseUrl).host, { timeout: resolveTimeout(30000) }).catch(() => {});
    await page.waitForLoadState("load", { timeout: resolveTimeout(30000) }).catch(() => {});
  }
}

module.exports = { SSO_ENTRY, adminKeycloakLoginId, dismissCookieBanner, env, oidcLogin };
