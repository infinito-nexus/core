const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");

const { decodeDotenvQuotedValue, normalizeBaseUrl, performKeycloakLoginForm, runAdminFlow, runBiberFlow, runGuestFlow } = require("./personas");
test.use({
  ignoreHTTPSErrors: true
});

const joomlaBaseUrl = normalizeBaseUrl(process.env.JOOMLA_BASE_URL);
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);

// Log out via the universal logout endpoint. Every app's nginx vhost intercepts
// `location = /logout` and proxies it to web-svc-logout. Using `waitUntil: 'commit'`
// avoids ERR_ABORTED from the multi-domain redirect chain.
async function joomlaLogout(page, baseUrl) {
  await page.goto(`${baseUrl.replace(/\/$/, "")}/logout`, { waitUntil: "commit" }).catch(() => {});
}

async function performJoomlaAdminFormLogin(page, baseUrl, username, password) {
  // Local Joomla form-login at /administrator?fallback=local. The
  // `?fallback=local` query short-circuits the plg_system_keycloak
  // redirect so the operator has an emergency hatch when Keycloak is
  // unavailable (per the documented Modus 3 contract).
  await page.goto(`${baseUrl}/administrator?fallback=local`, { waitUntil: "domcontentloaded" });

  const usernameField = page.locator("input[name='username']");
  const passwordField = page.locator("input[name='passwd']");

  await usernameField.waitFor({ state: "visible", timeout: 60_000 });
  await usernameField.fill(username);
  await passwordField.fill(password);

  await Promise.all([
    page.waitForLoadState("domcontentloaded"),
    page.locator("button[type='submit'], input[type='submit']").first().click(),
  ]);
}

test.beforeEach(async ({ page }) => {
  expect(joomlaBaseUrl, "JOOMLA_BASE_URL must be set in the Playwright env file").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set in the Playwright env file").toBeTruthy();
  await page.context().clearCookies();
});

test("OIDC: native plg_system_keycloak redirects unauthenticated visitors to Keycloak and logs them back in to Joomla", async ({ page }) => {
  // The plg_system_keycloak plugin shipped under
  // roles/web-app-joomla/files/joomla-oidc-plugin/ implements native
  // OIDC SSO against Keycloak (no oauth2-proxy sidecar). Visiting the
  // Joomla site root `/` while gated by the plugin redirects the
  // browser to the Keycloak authorization endpoint. After Keycloak
  // login, the plugin handles the callback at
  // /index.php?option=keycloak&task=callback, provisions/updates the
  // local Joomla user with RBAC group memberships derived from the
  // Keycloak `groups` claim, and lands the user back on the original
  // URL.
  skipUnlessServiceEnabled("oidc");
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set when OIDC is enabled").toBeTruthy();

  const expectedOidcAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;
  const expectedJoomlaBaseUrl = joomlaBaseUrl.replace(/\/$/, "");

  await page.goto(`${expectedJoomlaBaseUrl}/`);

  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: `expected redirect to Keycloak OIDC auth (${expectedOidcAuthUrl})`
    })
    .toContain(expectedOidcAuthUrl);

  await performKeycloakLoginForm(page, adminUsername, adminPassword);

  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: `expected redirect back to Joomla at ${expectedJoomlaBaseUrl}`
    })
    .toContain(expectedJoomlaBaseUrl);

  // Joomla front-end renders after the OIDC handshake. RBAC mapping
  // gave the administrator persona Super Users (id 8), so the
  // administrator landing nav link is visible to logged-in users.
  await expect(page.locator("body")).toBeVisible({ timeout: 60_000 });
});

test("OIDC: /administrator?fallback=local hatch bypasses Keycloak and accepts the local Joomla form (Modus 3 emergency path)", async ({ page }) => {
  // The local form-login fallback at /administrator?fallback=local
  // is the operationally-mandated hatch when Keycloak is unavailable
  // (per the documented Modus 3 contract). It MUST NOT redirect to the IdP,
  // and the local form MUST accept the bootstrap administrator
  // credentials.
  skipUnlessServiceEnabled("oidc");
  const expectedJoomlaBaseUrl = joomlaBaseUrl.replace(/\/$/, "");

  await performJoomlaAdminFormLogin(page, expectedJoomlaBaseUrl, adminUsername, adminPassword);

  // Joomla 6 uses `body.com_cpanel` on the admin home; the broader
  // fallback set covers future template tweaks.
  const controlPanelMarker = page
    .locator("body.com_cpanel, #sidebarmenu, nav[aria-label='Main menu'], a[href*='option=com_cpanel']")
    .first();
  await controlPanelMarker.waitFor({ state: "visible", timeout: 60_000 });
});

test("LDAP: Joomla core LDAP plugin authenticates the administrator at /administrator (LDAP variant)", async ({ page }) => {
  // In the LDAP variant (variant 1 of meta/variants.yml), the OIDC
  // service flag is off and Joomla's core LDAP authentication plugin
  // is the integrated login path against svc-db-openldap. This
  // scenario exercises that path.
  skipUnlessServiceEnabled("ldap");
  const expectedJoomlaBaseUrl = joomlaBaseUrl.replace(/\/$/, "");

  await page.goto(`${expectedJoomlaBaseUrl}/administrator`, { waitUntil: "domcontentloaded" });

  const usernameField = page.locator("input[name='username']");
  const passwordField = page.locator("input[name='passwd']");
  await usernameField.waitFor({ state: "visible", timeout: 60_000 });
  await usernameField.fill(adminUsername);
  await passwordField.fill(adminPassword);
  await Promise.all([
    page.waitForLoadState("domcontentloaded"),
    page.locator("button[type='submit'], input[type='submit']").first().click(),
  ]);

  // Body class on Joomla 5.x admin is `option-com_cpanel`; older releases used
  // `com_cpanel`. Match both, plus any `option-com_*` so first-login redirects
  // through `com_postinstall` don't false-fail the post-login assertion.
  const controlPanelMarker = page
    .locator("body.com_cpanel, body[class*='option-com_'], #sidebarmenu, nav[aria-label='Main menu'], a[href*='option=com_cpanel']")
    .first();
  // Race the success marker against Joomla's "Username and password do not
  // match" error. Without it, bad credentials make the test hang for the full
  // timeout per retry; with it, we fail fast with the actual error in the trace.
  const loginErrorAlert = page
    .locator(".alert-warning, .alert-danger, joomla-alert, [role='alert']")
    .filter({ hasText: /Username and password do not match|Login failed|invalid|incorrect/i })
    .first();
  await Promise.race([
    controlPanelMarker.waitFor({ state: "visible", timeout: 120_000 }),
    loginErrorAlert
      .waitFor({ state: "visible", timeout: 120_000 })
      .then(async () => {
        const errorText = (await loginErrorAlert.textContent().catch(() => "")) || "(unknown)";
        throw new Error(`Joomla rejected the admin login: ${errorText.trim()}`);
      }),
  ]);

  await joomlaLogout(page, expectedJoomlaBaseUrl);

  // After logout, /administrator must render the login form again rather than
  // the control panel.
  await page.goto(`${expectedJoomlaBaseUrl}/administrator`, { waitUntil: "domcontentloaded" }).catch(() => {});
  await expect(page.locator("input[name='username']")).toBeVisible({ timeout: 15_000 });
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
      // web-app-joomla admin-only interaction: open a management surface.
      const link = interactivePage
        .getByRole("link", { name: /^(administrator|users|content|menus|extensions|configuration)$/i })
        .first();
      if (await link.isVisible({ timeout: 10_000 }).catch(() => false)) {
        await link.click().catch(() => {});
        await interactivePage.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
        await expect(interactivePage.locator("body")).toContainText(
          /users|content|menus|extensions|configuration|articles/i,
          { timeout: 30_000 },
        );
      }
    },
  });
});
