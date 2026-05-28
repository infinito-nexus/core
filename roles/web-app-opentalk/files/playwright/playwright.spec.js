// End-to-end smoke tests for the OpenTalk role.
//
// Two scenarios mirroring the nextcloud convention:
//   1. administrator persona — SSO login lands on the OpenTalk dashboard.
//   2. biber persona — same flow in an isolated browser context.
const { test, expect } = require("@playwright/test");

const { decodeDotenvQuotedValue, runAdminFlow, runBiberFlow, runGuestFlow } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
test.use({ ignoreHTTPSErrors: true });

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

test("opentalk sso login (administrator) lands on dashboard", async ({ page }) => {
  skipUnlessServiceEnabled("oidc");
  expect(adminUsername, "LOGIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "LOGIN_PASSWORD must be set").toBeTruthy();

  await ssoLoginAndAssertDashboard(page, adminUsername, adminPassword);
});

test("opentalk sso login (biber) lands on dashboard", async ({ browser }) => {
  skipUnlessServiceEnabled("oidc");
  expect(biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  try {
    await ssoLoginAndAssertDashboard(page, biberUsername, biberPassword);
  } finally {
    await context.close();
  }
});

// Persona scenarios.
// Bodies live in the shared helper roles/test-e2e-playwright/files/personas.js
// so every role's persona flow stays consistent.

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

test("biber: app → universal logout", async ({ page }) => {
  await runBiberFlow(page);
});

test("administrator: app → universal logout", async ({ page }) => {
  await runAdminFlow(page, {
    adminInteraction: async (interactivePage) => {
      // web-app-opentalk admin-only interaction: open a management surface.
      const link = interactivePage
        .getByRole("link", { name: /^(admin|administration|rooms|users|invites)$/i })
        .first();
      if (await link.isVisible({ timeout: 10_000 }).catch(() => false)) {
        await link.click().catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /admin|rooms|users|invites|reports|administration/i,
          { timeout: 30_000 },
        );
      }
    },
  });
});
