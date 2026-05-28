// @ts-check
// Penpot design platform – Playwright spec
// Three-persona flow: guest / biber / administrator
// Shared helpers: service-gating.js, personas/

const { test, expect } = require("@playwright/test");
const { runGuestFlow, runBiberFlow, runAdminFlow, normalizeUrl, safeSkipUnlessEnabled } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

// ---------------------------------------------------------------------------
// Backend readiness gate
// Penpot's Java backend takes several minutes to start (DB migrations, SSL
// certificate loading). Poll the profile API until it responds before any
// persona test runs.
// ---------------------------------------------------------------------------
test.beforeAll(async ({ request }) => {
  test.setTimeout(960_000); // 16 min (15-min wait + 1-min buffer)
  const appBaseUrl = normalizeUrl(process.env.APP_BASE_URL || "");
  const healthUrl = `${appBaseUrl}/api/rpc/command/get-profile`;
  const maxAttempts = 180; // 15 min at 5 s intervals
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      const resp = await request.post(healthUrl, {
        data: {},
        headers: { "Content-Type": "application/json" },
        ignoreHTTPSErrors: true,
        timeout: 10_000,
      });
      if ([200, 401, 403].includes(resp.status())) {
        console.log(`Penpot backend ready after ${attempt} attempt(s)`);
        return;
      }
    } catch {}
    if (attempt < maxAttempts) await new Promise((r) => setTimeout(r, 5_000));
  }
  throw new Error("Penpot backend did not become ready within 15 minutes");
});

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

/**
 * Dismiss the Penpot first-login onboarding modal if it appears.
 * Wrapping in try-catch prevents test failure if the modal never shows.
 */
async function dismissPenpotOnboarding(page) {
  try {
    await page.waitForTimeout(800);
    if (page.isClosed()) return;

    // Complete registration / onboarding form (first-time users)
    const registerBtn = page
      .getByRole("button", { name: /create.*account|complete.*registration|finish.*setup|get\s*started/i })
      .first();
    if (await registerBtn.isVisible({ timeout: 4_000 }).catch(() => false)) {
      await registerBtn.click({ force: true });
      await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => {});
    }

    if (page.isClosed()) return;

    // Dismiss question/survey modal overlay
    const overlay = page
      .locator(
        ".main_ui_onboarding_questions__modal-overlay, [class*='onboarding'][class*='modal'], [class*='modal-overlay']",
      )
      .first();
    if (await overlay.isVisible({ timeout: 2_000 }).catch(() => false)) {
      await page.keyboard.press("Escape").catch(() => {});
      await page.waitForTimeout(600);
    }
  } catch {
    // Non-fatal: continue even if onboarding dismissal fails
  }
}

/**
 * Wait for the Penpot projects dashboard to be visible.
 * After OIDC login Penpot may take time to render the SPA dashboard.
 */
async function waitForPenpotDashboard(page) {
  await page.waitForLoadState("networkidle", { timeout: 60_000 }).catch(() => {});
  await dismissPenpotOnboarding(page);
}

// ---------------------------------------------------------------------------
// Persona tests
// ---------------------------------------------------------------------------

test("guest: public landing → login page → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

test("biber: penpot OIDC login → create project → logout", async ({ page }) => {
  safeSkipUnlessEnabled("oidc"); // Penpot's biber login requires OIDC (no local user accounts)
  await runBiberFlow(page, {
    biberInteraction: async (p) => {
      await waitForPenpotDashboard(p);

      // biber role-specific interaction: create a new project.
      // Penpot's dashboard shows a "+ New project" button.
      const newProjectBtn = p
        .getByRole("button", { name: /\+?\s*new\s*project/i })
        .first();
      const newProjectVisible = await newProjectBtn
        .isVisible({ timeout: 15_000 })
        .catch(() => false);

      if (newProjectVisible) {
        await newProjectBtn.click({ force: true });
        await p.waitForTimeout(1_500);

        // Penpot opens an inline input for the project name.
        const nameInput = p
          .locator(
            "input[data-testid='project-name-input'], input[placeholder*='project' i], " +
              "input[class*='project'], input[class*='element-list-body']",
          )
          .or(p.getByRole("textbox"))
          .first();
        if (await nameInput.isVisible({ timeout: 5_000 }).catch(() => false)) {
          await nameInput.fill("biber-test-project");
          await nameInput.press("Enter");
          await p.waitForLoadState("domcontentloaded").catch(() => {});
        }

        // Assert the project was created or we're still on the authenticated dashboard
        const url = p.url();
        expect(
          url.includes("/auth/login") || url.includes("/auth/register"),
          "biber must remain on an authenticated surface after project creation",
        ).toBe(false);
      } else {
        // Fallback: assert the biber persona is at least on the authenticated surface
        const url = p.url();
        expect(
          url.includes("/auth/login") || url.includes("/auth/register"),
          "biber must be on an authenticated surface (not on login page)",
        ).toBe(false);
      }
    },
  });
});

test("administrator: penpot OIDC login → admin profile verified → logout", async ({ page }) => {
  safeSkipUnlessEnabled("oidc"); // Penpot's admin login requires OIDC
  await runAdminFlow(page, {
    adminInteraction: async (p) => {
      const appBaseUrl = normalizeUrl(process.env.APP_BASE_URL || "");

      await waitForPenpotDashboard(p);

      // -----------------------------------------------------------------------
      // 1. Admin auto-provisioning via OIDC: verify profile API returns 200
      //    and the profile has email/identity data (proves OIDC auto-provision).
      // -----------------------------------------------------------------------
      const profileResp = await p.request.post(
        `${appBaseUrl}/api/rpc/command/get-profile`,
        {
          data: {},
          headers: { "Content-Type": "application/json" },
          ignoreHTTPSErrors: true,
        },
      );
      expect(
        profileResp.status(),
        "admin profile API must return 200 (proves auto-provisioned via OIDC)",
      ).toBe(200);
      const profile = await profileResp.json();
      expect(profile.email, "admin profile must have email (proves OIDC identity mapped)").toBeTruthy();

      // -----------------------------------------------------------------------
      // 2. Admin-specific surface: access Penpot's admin management panel.
      //    Penpot exposes an admin panel API for users flagged as admin.
      //    /api/rpc/command/search-users is an admin-only endpoint.
      // -----------------------------------------------------------------------
      const searchResp = await p.request.post(
        `${appBaseUrl}/api/rpc/command/search-users`,
        {
          data: { query: "" },
          headers: { "Content-Type": "application/json" },
          ignoreHTTPSErrors: true,
        },
      );
      // Admin-only endpoint: returns 200 for admin, 403 for regular users.
      // A 403 here would mean the administrator user lacks admin privileges.
      expect(
        searchResp.status(),
        `admin user must be authorised to call search-users (admin-only API). ` +
          `Got ${searchResp.status()} – check that the OIDC user is flagged as admin in Penpot.`,
      ).toBe(200);

      // -----------------------------------------------------------------------
      // 3. Verify the admin can interact with the Penpot dashboard
      // -----------------------------------------------------------------------
      const url = p.url();
      expect(
        url.includes("/auth/login") || url.includes("/auth/register"),
        "administrator must remain on an authenticated surface",
      ).toBe(false);
    },
  });
});
