// @ts-check
const { test, expect } = require('@playwright/test');
const { decodeDotenvQuotedValue, runAdminFlow, runBiberFlow, runGuestFlow } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

test.use({
  ignoreHTTPSErrors: true
});

const baseUrl       = decodeDotenvQuotedValue(process.env.DECIDIM_BASE_URL || process.env.APP_BASE_URL);
const adminEmail    = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const biberEmail    = decodeDotenvQuotedValue(process.env.BIBER_EMAIL);
const oidcIssuerUrl = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL);

test.beforeEach(() => {
  expect(baseUrl,       "DECIDIM_BASE_URL must be set in the Playwright env file").toBeTruthy();
  expect(adminEmail,    "ADMIN_EMAIL must be set in the Playwright env file").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set in the Playwright env file").toBeTruthy();
  expect(biberUsername, "BIBER_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set in the Playwright env file").toBeTruthy();
  expect(biberEmail,    "BIBER_EMAIL must be set in the Playwright env file").toBeTruthy();
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set in the Playwright env file").toBeTruthy();
});

// Helper: local form login (admin only)
async function login(page, email, password) {
  await page.goto(`${baseUrl}/users/sign_in`);
  await page.waitForLoadState("networkidle");
  const cookieBanner = page.locator("#dc-dialog-wrapper, .cookies__container, [data-cookie-consent]");
  if (await cookieBanner.isVisible().catch(() => false)) {
    const acceptBtn = page.locator("button[data-dc-accept], button.cookies__accept, button:has-text('Accept')").first();
    if (await acceptBtn.isVisible().catch(() => false)) {
      await acceptBtn.click();
      await page.waitForLoadState("networkidle");
    }
  }
  const emailInput = page.getByLabel(/email/i).first();
  await emailInput.waitFor({ state: "attached", timeout: 60000 });
  await emailInput.fill(email);
  await page.locator("input[type='password']").first().fill(password);
  await page.getByRole('button', { name: /log in|sign in/i }).first().click();
  await page.waitForLoadState("networkidle");
}

// Helper: dismiss the cookie consent banner if present. Decidim renders a
// modal overlay that steals pointer events from form buttons — without this
// the "Create an account" submit on the OIDC registration form is not hittable.
async function dismissCookieBanner(page) {
  const acceptBtn = page.getByRole("button", { name: /accept all|accept only essential|accept/i }).first();
  if (await acceptBtn.isVisible().catch(() => false)) {
    await acceptBtn.click().catch(() => {});
    await page.waitForLoadState("networkidle", { timeout: 5000 }).catch(() => {});
  }
}

// Helper: OIDC login via Keycloak
async function oidcLogin(page, username, password) {
  await page.goto(`${baseUrl}/users/sign_in`);
  await page.waitForLoadState("networkidle");
  await dismissCookieBanner(page);
  const ssoButton = page.locator("a[href*='openid_connect']").first();
  const ssoVisible = await ssoButton.isVisible().catch(() => false);
  if (!ssoVisible) {
    return null; // OIDC not configured
  }
  // Submit form manually replicating Rails UJS data-method="post"
  const ssoHref = await ssoButton.getAttribute("href");
  console.log("SSO href:", ssoHref);
  await page.waitForFunction(() => document.readyState === "complete");
  const navigated = page.waitForURL(/auth\.infinito\.example/, { timeout: 30000 });
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
  console.log("Current URL:", page.url());
  // Fill Keycloak login form
  await page.getByRole("textbox", { name: /username|email/i }).fill(username);
  await page.getByRole("textbox", { name: /password/i }).fill(password);
  await page.locator("#kc-login").click();
  console.log("Login clicked, waiting for redirect back...");
  await page.waitForLoadState("networkidle", { timeout: 30000 }).catch(e => console.log("networkidle error:", e.message));
  console.log("After login URL:", page.url());
  await dismissCookieBanner(page);

  // First-time OIDC users land on Decidim's registration form (TOS + nickname
  // confirmation). Returning users skip this and sign in directly — detection
  // is by form presence, not URL, so the flow is idempotent across runs.
  const tosCheckbox = page.locator("input[type='checkbox'][name='user[tos_agreement]']").first();
  const onRegistrationForm = await tosCheckbox.isVisible().catch(() => false);
  if (onRegistrationForm) {
    console.log("First-time OIDC registration form detected, accepting TOS...");
    await tosCheckbox.check({ force: true });
    // Decidim's `user-registration-form` Stimulus controller cancels submit and
    // opens a newsletter modal when `user[newsletter]` is unchecked. Click the
    // decline button on that modal to proceed without subscribing — that path
    // sets the continue flag and re-submits the form.
    await page.evaluate(() => document.getElementById("omniauth-register-form").requestSubmit());
    const declineBtn = page.locator("#sign-up-newsletter-modal [data-check='false']").first();
    await declineBtn.waitFor({ state: "visible", timeout: 10000 });
    await Promise.all([
      page.waitForURL((url) => !/auth\/openid_connect\/callback/.test(url.toString()), { timeout: 30000 }).catch(e => console.log("post-submit nav error:", e.message)),
      declineBtn.click({ force: true }),
    ]);
    console.log("After registration URL:", page.url());
  }
}

// Scenario I: Homepage loads
test("homepage loads and shows Decidim", async ({ page }) => {
  await page.goto(baseUrl);
  await expect(page).not.toHaveTitle("");
  await expect(page.locator("body")).toBeVisible();
});

// Scenario II: Admin local login and logout
test("admin can log in and out", async ({ page }) => {
  await login(page, adminEmail, adminPassword);
  await expect(page).not.toHaveURL(/sign_in/);
  await expect(page.locator("body")).toBeVisible();
  await page.goto(`${baseUrl}/users/sign_out`);
  await page.waitForLoadState("networkidle");
  await expect(page).not.toHaveURL(/sign_in/);
});

// Scenario III: Biber OIDC login and logout
test("biber can log in via OIDC and log out", async ({ page }) => {
  const result = await oidcLogin(page, biberUsername, biberPassword);
  if (result === null) { test.skip(); return; }
  await expect(page).not.toHaveURL(/sign_in/);
  await expect(page.locator("body")).toBeVisible();
  await page.goto(`${baseUrl}/users/sign_out`);
  await page.waitForLoadState("networkidle");
  await expect(page).not.toHaveURL(/sign_in/);
});

// Scenario IV: Admin and biber can communicate via conversations
test("biber can access profile after OIDC login", async ({ page }) => {
  // Biber logs in via OIDC
  const result = await oidcLogin(page, biberUsername, biberPassword);
  if (result === null) { test.skip(); return; }
  await expect(page).not.toHaveURL(/sign_in/);

  // Biber accesses their account page
  await page.goto(`${baseUrl}/account`);
  await page.waitForLoadState("networkidle");
  await expect(page).not.toHaveURL(/sign_in/);
  await expect(page.locator("h1, h2").first()).toBeVisible();
});

// Scenario V: SSO button visible when OIDC is enabled
test("SSO login button is visible when OIDC is enabled", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  await page.goto(`${baseUrl}/users/sign_in`);
  await page.waitForLoadState("networkidle");
  const ssoButton = page.locator("a[href*='openid_connect']").first();
  await expect(ssoButton).toBeVisible();
});

// Persona scenarios.
// Bodies live in the shared helper roles/test-e2e-playwright/files/personas.js
// so every role's persona flow stays consistent.

test("biber: app → universal logout", async ({ page }) => {
  await runBiberFlow(page);
});

test("administrator: app → universal logout", async ({ page }) => {
  await runAdminFlow(page, {
    adminInteraction: async (interactivePage) => {
      // web-app-decidim admin-only interaction: open a management surface.
      const link = interactivePage
        .getByRole("link", { name: /^(admin|administration|configuration|participants)$/i })
        .first();
      if (await link.isVisible({ timeout: 10_000 }).catch(() => false)) {
        await link.click().catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /admin|administration|participants|processes|assemblies|moderation/i,
          { timeout: 30_000 },
        );
      }
    },
  });
});

// Persona scenarios.
// Bodies live in the shared persona helpers under
// roles/test-e2e-playwright/files/personas/{guest,biber,admin}.js.

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

require("./test-seaweedfs");
