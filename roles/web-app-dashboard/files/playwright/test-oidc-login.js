const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { decodeDotenvQuotedValue, isVisible, normalizeBaseUrl } = require("./personas");

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const loginUsername = decodeDotenvQuotedValue(process.env.LOGIN_USERNAME);
const loginPassword = decodeDotenvQuotedValue(process.env.LOGIN_PASSWORD);
const expectedOidcAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;

async function waitForFirstVisible(locators, timeout, errorMessage) {
  const deadline = Date.now() + timeout;

  while (Date.now() < deadline) {
    for (const locator of locators) {
      const candidate = locator.first();

      if (await candidate.isVisible().catch(() => false)) {
        return candidate;
      }
    }

    await new Promise((resolve) => setTimeout(resolve, 250));
  }

  throw new Error(errorMessage);
}

async function getHeaderNavigation(page) {
  const headerNav = page.locator("nav.menu-header").first();
  await expect(headerNav).toBeVisible({ timeout: resolveTimeout(60_000) });
  return headerNav;
}

async function getHeaderAuthControls(page) {
  const headerNav = await getHeaderNavigation(page);
  const loginTrigger = headerNav.locator("a, button").filter({ hasText: /login/i }).first();
  const accountTrigger = headerNav.getByRole("button", { name: /account/i }).first();
  const accountMenu = headerNav.locator(".dropdown-menu").filter({ hasText: /logout/i }).first();

  return { loginTrigger, accountTrigger, accountMenu };
}

async function expectLoggedOutHeaderAuthState(page) {
  const controls = await getHeaderAuthControls(page);

  await expect
    .poll(async () => await isVisible(controls.loginTrigger), {
      timeout: resolveTimeout(60_000),
      message: "Expected dashboard OIDC JavaScript to expose Login before authentication",
    })
    .toBe(true);

  await expect
    .poll(async () => await isVisible(controls.accountTrigger), {
      timeout: resolveTimeout(60_000),
      message: "Expected dashboard OIDC JavaScript to keep Account hidden before authentication",
    })
    .toBe(false);

  return controls;
}

async function expectLoggedInHeaderAuthState(page) {
  const controls = await getHeaderAuthControls(page);

  await expect
    .poll(async () => await isVisible(controls.accountTrigger), {
      timeout: resolveTimeout(60_000),
      message: "Expected dashboard OIDC JavaScript to automatically switch the header button to Account",
    })
    .toBe(true);

  await expect(controls.accountTrigger).toContainText(/Account/, { timeout: resolveTimeout(60_000) });

  await expect
    .poll(async () => await isVisible(controls.loginTrigger), {
      timeout: resolveTimeout(60_000),
      message: "Expected dashboard OIDC JavaScript to hide Login after authentication",
    })
    .toBe(false);

  return controls;
}

async function isDropdownMenuOpen(trigger, menu) {
  const expanded = await trigger.getAttribute("aria-expanded").catch(() => null);
  const menuRoot = menu.first();
  const menuHasShowClass = await menuRoot.evaluate((element) => element.classList.contains("show")).catch(() => false);
  const menuVisible = await menuRoot.isVisible().catch(() => false);
  const interactiveItemVisible = await menuRoot
    .locator("a, button, [role='menuitem'], [role='link']")
    .first()
    .isVisible()
    .catch(() => false);

  return expanded === "true" || (menuVisible && (menuHasShowClass || interactiveItemVisible));
}

async function waitForDropdownMenuOpen(trigger, menu, label, timeout = resolveTimeout(3_000)) {
  await expect
    .poll(async () => isDropdownMenuOpen(trigger, menu), {
      timeout,
      message: `Expected the ${label} dropdown menu to open`,
    })
    .toBe(true);
}

async function openDropdownMenu(trigger, menu, label) {
  if (await isDropdownMenuOpen(trigger, menu)) {
    return;
  }

  const openAttempts = [
    async () => trigger.click(),
    async () => trigger.hover(),
    async () => trigger.press("Enter"),
    async () => trigger.press(" "),
    async () => trigger.click({ force: true }),
    async () =>
      trigger.evaluate((element) => {
        element.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: window }));
      }),
  ];

  for (const attempt of openAttempts) {
    await attempt().catch(() => {});

    try {
      await waitForDropdownMenuOpen(trigger, menu, label, resolveTimeout(2_500));
      return;
    } catch {
      // Try the next interaction strategy.
    }
  }

  throw new Error(`Unable to open the ${label} dropdown menu`);
}

async function findAccountLogoutItem(accountMenu) {
  return waitForFirstVisible(
    [
      accountMenu.getByRole("link", { name: /logout/i }),
      accountMenu.locator("a[href*='logout'], a[href*='signout'], a[href*='sign-out']"),
      accountMenu.locator("a, button, [role='link']").filter({ hasText: /logout/i }),
    ],
    10_000,
    "Timed out waiting for the Account logout entry"
  );
}

async function confirmLogoutIfNeeded(page) {
  const logoutConfirmCandidates = [
    page.getByRole("button", { name: /logout|sign out|continue/i }),
    page.locator("button[type='submit'], input[type='submit'], #kc-logout, #kc-logout-confirm"),
  ];

  const logoutConfirmButton = await waitForFirstVisible(
    logoutConfirmCandidates,
    5_000,
    "Timed out waiting for an optional Keycloak logout confirmation button"
  ).catch(() => null);

  if (logoutConfirmButton) {
    await logoutConfirmButton.click().catch(() => {});
  }
}

exports.register = function (shared) {
  test("dashboard login automatically switches Login to Account and exposes Logout under Account", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    const diagnostics = shared.attachDiagnostics(page);

    await page.goto("/");
    await shared.waitForDashboardReady(page);
    await shared.waitForResourceResponse(diagnostics.responses, `${shared.env.dashboardJsBaseUrl}/oidc.js`, "dashboard oidc script");

    const loggedOutControls = await expectLoggedOutHeaderAuthState(page);
    await loggedOutControls.loginTrigger.click();

    const usernameField = page.locator("input[name='username'], input#username").first();
    const passwordField = page.locator("input[name='password'], input#password").first();
    const signInButton = page.locator("input#kc-login, button#kc-login, button[type='submit'], input[type='submit']").first();

    await expect
      .poll(
        async () => page.url().includes(expectedOidcAuthUrl) || (await isVisible(usernameField)),
        {
          timeout: resolveTimeout(60_000),
          message: `Expected the dashboard login flow to reach the Keycloak auth page: ${expectedOidcAuthUrl}`,
        }
      )
      .toBe(true);

    await expect(usernameField).toBeVisible({ timeout: resolveTimeout(60_000) });
    await usernameField.fill(loginUsername);
    await passwordField.fill(loginPassword);
    await signInButton.click();

    await expect
      .poll(async () => page.url().startsWith(appBaseUrl), {
        timeout: resolveTimeout(60_000),
        message: `Expected Keycloak login to redirect back to the dashboard: ${appBaseUrl}`,
      })
      .toBe(true);

    await shared.waitForDashboardReady(page);
    const loggedInControls = await expectLoggedInHeaderAuthState(page);
    await openDropdownMenu(loggedInControls.accountTrigger, loggedInControls.accountMenu, "Account");

    const logoutEntry = await findAccountLogoutItem(loggedInControls.accountMenu);
    await expect(logoutEntry).toBeVisible({ timeout: resolveTimeout(10_000) });
    await expect(logoutEntry).toContainText(/logout/i);
    await logoutEntry.click();

    await expect
      .poll(
        async () =>
          page.url().includes("/protocol/openid-connect/logout") || page.url().startsWith(appBaseUrl),
        {
          timeout: resolveTimeout(30_000),
          message: "Expected dashboard logout to reach Keycloak logout or redirect back to the dashboard",
        }
      )
      .toBe(true);

    if (page.url().includes("/protocol/openid-connect/logout")) {
      await confirmLogoutIfNeeded(page);
    }

    await page.goto("/");
    await shared.waitForDashboardReady(page);
    await expectLoggedOutHeaderAuthState(page);
  });
};
