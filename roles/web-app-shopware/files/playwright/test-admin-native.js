const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { decodeDotenvQuotedValue, normalizeBaseUrl , gotoOnion } = require("./personas");
const { performKeycloakLogin } = require("./personas/utils/keycloak");
const { confirmKeycloakLogoutIfPrompted } = require("./personas/utils/logout");

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");
const ssoEnabled = (process.env.SSO_SERVICE_ENABLED || "").toLowerCase() === "true";
const logoutEnabled = (process.env.LOGOUT_SERVICE_ENABLED || "").toLowerCase() === "true";
const logoutBaseUrl = normalizeBaseUrl(process.env.LOGOUT_URL || "");

async function signIn(page) {
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();

  await page.context().clearCookies();
  await gotoOnion(page, `${appBaseUrl}/admin`, { waitUntil: "domcontentloaded" });

  if (ssoEnabled) {
    expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();

    const ssoButton = page
      .locator("a.heptacom-admin-open-auth--button")
      .filter({ hasText: /keycloak/i })
      .first();
    await expect(
      ssoButton,
      "AdminOpenAuth appends its provider link into .sw-login__content; a missing link means the plugin is inactive or the client row is not active",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    await ssoButton.click();
    await performKeycloakLogin(page, adminUsername, adminPassword, canonicalDomain);
  } else {
    const password = page.locator("input[type='password']:visible").first();
    await expect(
      password,
      "the administration SPA must paint its login form; a blank shell here means the admin bundle never booted",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    await page.locator("input[name$='username']:visible").first().fill(adminUsername);
    await password.fill(adminPassword);
    await password.press("Enter");
  }

  const userActions = page.locator(".sw-admin-menu__user-actions-toggle");
  await expect(
    userActions,
    "the admin menu must render after login; still on the login form means the credentials were rejected",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
  return userActions;
}

async function dismissFirstRunWizard(page) {
  const wizard = page.locator(".sw-first-run-wizard-modal");
  const shown = await wizard
    .waitFor({ state: "visible", timeout: resolveTimeout(15_000) })
    .then(() => true)
    .catch(() => false);
  if (!shown) {
    return;
  }
  await gotoOnion(page, `${appBaseUrl}/admin#/sw/dashboard/index`);
  await expect(
    wizard,
    "the first-run wizard renders :closable=false on its first step, so leaving its route is the only exit",
  ).toBeHidden({ timeout: resolveTimeout(30_000) });
}

async function clickLogout(page) {
  await page.locator(".sw-admin-menu__user-actions-toggle").click();
  const logout = page.locator(".sw-admin-menu__logout-action");
  await expect(logout, "Shopware's logout lives behind the user-actions toggle").toBeVisible({
    timeout: resolveTimeout(15_000),
  });
  await logout.click();
}

test("administrator: admin login → catalogue → in-app logout", async ({ page }) => {
  test.setTimeout(resolveTimeout(180_000));

  await signIn(page);

  await expect(page.locator("body")).toContainText(/dashboard|catalogue|catalog|order|product/i, {
    timeout: resolveTimeout(60_000),
  });

  await dismissFirstRunWizard(page);
  await clickLogout(page);
  await confirmKeycloakLogoutIfPrompted(page);
  await expect
    .poll(
      async () => (await page.context().cookies()).some((c) => c.name === "bearerAuth"),
      {
        message:
          "web-svc-logout clears the cookie with Clear-Site-Data on its conductor page, which Keycloak's logout page frames; navigating away before that page loads leaves the admin cookie alive",
        timeout: resolveTimeout(30_000),
      },
    )
    .toBe(false);
  await gotoOnion(page, `${appBaseUrl}/admin`, { waitUntil: "domcontentloaded" });

  await expect(
    page.locator("input[type='password']:visible").first(),
    "after logout the administration must fall back to its login form",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
});

test("administrator: the admin session outlives a logout whose sweep never lands", async ({
  page,
}) => {
  test.setTimeout(resolveTimeout(180_000));
  test.skip(
    !ssoEnabled || !logoutEnabled,
    "the sweep only exists where Keycloak frames web-svc-logout",
  );

  const conductorOrigin = logoutBaseUrl ? new URL(logoutBaseUrl).origin : "";
  const isConductor = (url) =>
    (conductorOrigin !== "" && url.origin === conductorOrigin) ||
    (url.pathname === "/" && url.searchParams.has("sid") && url.searchParams.has("iss"));

  await signIn(page);
  await dismissFirstRunWizard(page);

  const attempted = [];
  const blocked = [];
  page.on("request", (request) => {
    if (isConductor(new URL(request.url()))) {
      attempted.push(request.url());
    }
  });
  await page.route(
    (url) => isConductor(url),
    (route) => {
      blocked.push(route.request().url());
      return route.abort();
    },
  );

  await clickLogout(page);
  await confirmKeycloakLogoutIfPrompted(page);

  const deadline = Date.now() + resolveTimeout(30_000);
  while (attempted.length === 0 && Date.now() < deadline) {
    await page.waitForTimeout(resolveTimeout(500));
  }

  test.skip(
    attempted.length === 0,
    "Keycloak never framed the conductor here, so blocking it proves nothing; making it land is the sibling test's assertion, not this one's",
  );
  expect(
    blocked.length,
    "the conductor was requested but page.route let it through, so the abort is a no-op and the cookie assertion below would be meaningless",
  ).toBeGreaterThan(0);

  await gotoOnion(page, `${appBaseUrl}/admin`, { waitUntil: "domcontentloaded" });

  expect(
    (await page.context().cookies()).some((c) => c.name === "bearerAuth"),
    "with the conductor blocked the admin cookie must survive: its Clear-Site-Data header is what deletes it across the registrable domain, and the injected logout redirect preempts Shopware's own clearAuthState, so the sibling test's wait is load-bearing rather than decorative",
  ).toBe(true);
});
