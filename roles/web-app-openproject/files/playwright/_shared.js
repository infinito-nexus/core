const { expect } = require("@playwright/test");
const { runAdminFlow } = require("./personas");
const { resolveTimeout } = require("./timeouts");

/**
 * Skip the guided tour OpenProject starts on a first login.
 *
 * @param {import('@playwright/test').Page} page authenticated browser page
 */
async function skipOnboardingTour(page) {
  if (!new URL(page.url()).searchParams.has("first_time_user")) return;
  const skip = page.locator(".enjoyhint_skip_btn");
  const shown = await skip
    .waitFor({ state: "visible", timeout: resolveTimeout(15_000) })
    .then(() => true)
    .catch(() => false);
  if (!shown) return;
  await skip.click({ timeout: resolveTimeout(10_000) });
  await expect(
    page.locator(".enjoyhint"),
    "skipping the first-login onboarding tour must remove its overlay, which otherwise swallows every click on the page",
  ).toBeHidden({ timeout: resolveTimeout(10_000) });
}

/**
 * Click into an OpenProject management surface.
 *
 * @param {import('@playwright/test').Page} page authenticated browser page
 */
async function openManagementSurface(page) {
  await skipOnboardingTour(page);
  const link = page
    .getByRole("link", { name: /^(projects|work packages|admin)$/i })
    .first();
  if (!(await link.isVisible().catch(() => false))) return;
  await link.click({ timeout: resolveTimeout(30_000) }).catch(() => {});
  await page
    .waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) })
    .catch(() => {});
  await expect(page.locator("body")).toContainText(
    /project|work package|backlog|openproject/i,
    { timeout: resolveTimeout(30_000) },
  );
}

/**
 * Run `assertions` against a live administrator session.
 *
 * `runAdminFlow` is a whole journey and ends in `inAppLogout` plus
 * `assertUnauthenticatedLanding`, so anything placed AFTER it talks to the app
 * anonymously -- an `/api/v3` read then answers 302 (oauth2-proxy gate) or 401
 * (native session). The `adminInteraction` seam is the only point at which the
 * session is established, which is why the assertions run from inside it; the
 * surface it opens first is also what makes the logout control reachable.
 *
 * @param {import('@playwright/test').Page} page browser page to authenticate
 * @param {(page: import('@playwright/test').Page) => Promise<void>} assertions
 *   role-specific checks, run while the administrator session is live
 */
async function withAdminSession(page, assertions) {
  await runAdminFlow(page, {
    adminInteraction: async (interactivePage) => {
      await openManagementSurface(interactivePage);
      await assertions(interactivePage);
    },
  });
}

module.exports = { openManagementSurface, withAdminSession };
