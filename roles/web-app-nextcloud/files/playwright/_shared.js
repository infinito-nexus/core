// Shared Nextcloud Playwright spec state: env vars, locator helpers, modal
// dismissal, login/logout flow, and the `beforeEach` env-presence guard.
// `playwright.spec.js` wires the lifecycle hook and `require()`s one test
// module per scenario so each test stays atomar. Talk-admin-specific
// helpers and env decoding live in `test-talk-admin-settings.js`.

const { expect } = require("@playwright/test");
const { decodeDotenvQuotedValue, findFirstVisibleCandidate, runAdminFlow, runBiberFlow, runGuestFlow } = require("./personas");
const { isServiceEnabled } = require("./service-gating");

// ---------------------------------------------------------------------------
// Env decoding
//
// All values originate from the rendered `.env` under the staging dir.
// `docker --env-file` preserves the quotes emitted by `dotenv_quote`, so
// normalize these values before building URLs or typing credentials.
// ---------------------------------------------------------------------------
const loginUsername = decodeDotenvQuotedValue(process.env.LOGIN_USERNAME);
const loginPassword = decodeDotenvQuotedValue(process.env.LOGIN_PASSWORD);
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const nextcloudDirectLoginPassword = decodeDotenvQuotedValue(process.env.NEXTCLOUD_DIRECT_LOGIN_PASSWORD) || loginPassword;
const oidcIssuerUrl = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL);
const nextcloudBaseUrl = decodeDotenvQuotedValue(process.env.NEXTCLOUD_BASE_URL);
const nextcloudUsernameFieldPattern = /account name(?: or email)?|username(?: or email)?/i;
const nextcloudCredentialSubmitPattern = /^(sign in|log in)$/i;

// Condition variables driving the login flavor. Ansible renders these from the
// role's services.{oidc,ldap}.enabled (meta/services.yml) so the spec never has to
// sniff which login UI shape the deployment exposes:
//   - OIDC + LDAP  -> "oidc_login"  (pulsejet/nextcloud-oidc-login,
//                                    auto_redirect hands straight to Keycloak)
//   - OIDC only    -> "sociallogin" (nextcloud/sociallogin shows a
//                                    "Log in with Keycloak" entry first)
//   - no OIDC      -> "native"      (no Keycloak handoff; NC credential form)
const nextcloudOidcEnabled = isServiceEnabled("oidc");
const nextcloudLdapEnabled = isServiceEnabled("ldap");
const nextcloudLoginFlavor = !nextcloudOidcEnabled
  ? "native"
  : nextcloudLdapEnabled
    ? "oidc_login"
    : "sociallogin";

// ---------------------------------------------------------------------------
// Locator helpers
//
// Nextcloud renders different "shell" containers depending on the app (Vue
// vs. legacy) and version. The selectors below match any of them so the
// tests work across NC 28+ without hard-coding one layout.
// ---------------------------------------------------------------------------

function getNextcloudShellCandidates(target) {
  return [
    {
      kind: "shell",
      // #app-content-vue: dashboard and Vue-based apps.
      // #app-navigation-vue: Vue sidebar (files etc.).
      // #app-content: legacy app container.
      // #header-start__appmenu: always present in layout.user.php <nav>.
      locator: target.locator("#app-content-vue, #app-navigation-vue, #app-content, #header-start__appmenu")
    },
    {
      kind: "shell",
      locator: target.locator('a[href*="/apps/files"], a[href*="/apps/dashboard"]')
    }
  ];
}

async function waitForFirstVisible(page, locators, timeout = 60_000) {
  const deadline = Date.now() + timeout;

  while (Date.now() < deadline) {
    for (const locator of locators) {
      if (await locator.first().isVisible().catch(() => false)) {
        return locator.first();
      }
    }

    await page.waitForTimeout(500);
  }

  throw new Error("Timed out waiting for one of the expected Nextcloud selectors to become visible");
}

async function waitForVisibleCandidate(
  page,
  candidates,
  timeout = 60_000,
  errorMessage = "Timed out waiting for one of the expected Nextcloud selectors to become visible"
) {
  const deadline = Date.now() + timeout;

  while (Date.now() < deadline) {
    const visibleCandidate = await findFirstVisibleCandidate(candidates);

    if (visibleCandidate) {
      return visibleCandidate;
    }

    await page.waitForTimeout(500);
  }

  throw new Error(errorMessage);
}

// ---------------------------------------------------------------------------
// Modal / user-menu helpers
//
// Fresh Nextcloud accounts see stacked onboarding dialogs (first-run wizard,
// "What's new", recommended apps). They intercept pointer events and break
// any follow-up click (e.g. on the user menu), so dismiss them aggressively
// and retry the user-menu click if the overlay reappears.
// ---------------------------------------------------------------------------

async function dismissBlockingNextcloudModals(page, nextcloudFrame, maxDismissals = 4) {
  const modalOverlay = nextcloudFrame.locator(
    "#firstrunwizard.modal-mask, #firstrunwizard[role='dialog'], .modal-mask[role='dialog'], [role='dialog'][aria-modal='true']"
  );
  const dismissButtonCandidates = [
    nextcloudFrame.getByRole("button", { name: /^close$/i }),
    nextcloudFrame.getByRole("button", { name: /^schlie(?:ss|ß)en$/i }),
    nextcloudFrame.locator(
      ".modal-mask .modal-container__close, .modal-mask .header-close, [role='dialog'] .modal-container__close, [role='dialog'] .header-close"
    ),
    nextcloudFrame.locator(
      ".modal-mask .next, .modal-mask button[aria-label='Next'], [role='dialog'] .next, [role='dialog'] button[aria-label='Next']"
    ),
    nextcloudFrame.getByRole("button", { name: /skip|not now|later|dismiss|done|got it/i })
  ];
  let stableChecksWithoutModal = 0;

  for (let i = 0; i < maxDismissals; i += 1) {
    if (!(await modalOverlay.first().isVisible().catch(() => false))) {
      stableChecksWithoutModal += 1;
      if (stableChecksWithoutModal >= 2) {
        return;
      }
      await page.waitForTimeout(600);
      continue;
    }

    stableChecksWithoutModal = 0;
    let dismissed = false;

    for (const candidate of dismissButtonCandidates) {
      const button = candidate.first();
      if (await button.isVisible().catch(() => false)) {
        await button.click({ timeout: 2_000 }).catch(() => {});
        dismissed = true;
        break;
      }
    }

    if (!dismissed) {
      await page.keyboard.press("Escape").catch(() => {});
    }

    await page.waitForTimeout(300);
  }
}

async function clickUserMenuWithModalRetry(page, nextcloudFrame, userMenuLocator, attempts = 5) {
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    await dismissBlockingNextcloudModals(page, nextcloudFrame, 6);

    try {
      await userMenuLocator.click({ timeout: 4_000 });
      return;
    } catch (error) {
      const message = String(error && error.message ? error.message : error);
      const retriable = /intercepts pointer events|timed out|timeout/i.test(message);

      if (!retriable || attempt === attempts) {
        throw error;
      }
      await page.waitForTimeout(500);
    }
  }
}

// ---------------------------------------------------------------------------
// Social-login entry points
//
// Some NC login layouts show an explicit "Log in with <provider>" button
// before the credential form. Detect it so the dashboard flow can click
// through to the Keycloak form regardless of which variant renders.
// ---------------------------------------------------------------------------

function getNextcloudSocialLoginCandidates(target) {
  // The third "alternative login" shape is `pulsejet/nextcloud-oidc-login`
  // (the one this role actually deploys for the OIDC+LDAP flavor). It renders
  // as `<a href="/apps/oidc_login/oidc" class="oidc-button">`. Match it
  // explicitly so the test can click through even if `oidc_login_auto_redirect`
  // does not bounce the request — which can race during cold first-deploys.
  return [
    {
      kind: "social-login",
      locator: target.locator(
        'a[href*="/apps/sociallogin/"], a[href*="/custom_oidc/"], a[href*="/apps/oidc_login/"], a.oidc-button, button[formaction*="/apps/sociallogin/"], button[formaction*="/custom_oidc/"]'
      )
    },
    {
      kind: "social-login",
      locator: target.getByRole("link", { name: /log in with|sign in with|continue with|openid connect/i })
    },
    {
      kind: "social-login",
      locator: target.getByRole("button", { name: /log in with|sign in with|continue with|openid connect/i })
    }
  ];
}

// ---------------------------------------------------------------------------
// SSO login flow (standalone page, no dashboard iframe)
//
// `oidc_login_auto_redirect=true` together with `oidc_login_hide_password_form=true`
// means visiting `/login` immediately bounces to Keycloak and never renders
// the native NC credential form. So this helper:
//   - goes to `/login`,
//   - accepts either the Keycloak credential form OR an already-signed-in
//     NC shell (for reused browser contexts),
//   - fills Keycloak creds and waits for the NC shell to reappear.
// ---------------------------------------------------------------------------

async function loginToStandaloneNextcloud(adminPage, username = loginUsername, password = loginPassword) {
  const loginUrl = new URL("login", nextcloudBaseUrl).toString();
  const usernameField = adminPage.getByRole("textbox", { name: nextcloudUsernameFieldPattern });
  const passwordField = adminPage.locator('input[name="password"], input[type="password"]').first();
  const signInButton = adminPage.getByRole("button", { name: nextcloudCredentialSubmitPattern });
  const standaloneShellCandidates = getNextcloudShellCandidates(adminPage);

  await adminPage.goto(loginUrl, {
    waitUntil: "commit",
    timeout: 60_000
  }).catch(() => {});

  const credentialCandidates = [
    { kind: "credentials", locator: usernameField },
    { kind: "credentials", locator: signInButton }
  ];
  const socialLoginCandidates = getNextcloudSocialLoginCandidates(adminPage);

  let flavorCandidates;
  let timeoutMessage;
  switch (nextcloudLoginFlavor) {
    case "native":
      flavorCandidates = [...credentialCandidates, ...standaloneShellCandidates];
      timeoutMessage =
        "Timed out waiting for the Nextcloud native credential form or an already-authenticated shell";
      break;
    case "sociallogin":
      flavorCandidates = [
        ...socialLoginCandidates,
        ...credentialCandidates,
        ...standaloneShellCandidates
      ];
      timeoutMessage =
        "Timed out waiting for the Nextcloud social-login entry, the Keycloak credential form, or an already-authenticated shell";
      break;
    case "oidc_login":
    default:
      // Happy path: `oidc_login_auto_redirect=true` bounces /login straight to
      // Keycloak, so the Keycloak credential form (`credentialCandidates`) or
      // an already-authenticated NC shell appears. Race path: under cold
      // first-deploy load the upstream `boot()` hook can lose its
      // `header(Location:...)` (headers already sent by an earlier hook), and
      // /login renders the NC login chrome with the password form hidden but
      // the OIDC alt-login button visible. Treat that button as a valid entry
      // point so the test still proceeds via an explicit click instead of
      // timing out.
      flavorCandidates = [
        ...credentialCandidates,
        ...socialLoginCandidates,
        ...standaloneShellCandidates
      ];
      timeoutMessage =
        "Timed out waiting for the Keycloak login form, the OIDC alt-login button, or an already-authenticated Nextcloud shell";
      break;
  }

  const initialState = await waitForVisibleCandidate(
    adminPage,
    flavorCandidates,
    60_000,
    timeoutMessage
  );

  if (initialState.kind === "shell") {
    await dismissBlockingNextcloudModals(adminPage, adminPage);
    return;
  }

  if (initialState.kind === "social-login") {
    await initialState.locator.click({ timeout: 5_000 });
    await waitForVisibleCandidate(
      adminPage,
      [...credentialCandidates, ...standaloneShellCandidates],
      60_000,
      "Timed out waiting for the Keycloak credential form after following the Nextcloud social-login entry"
    );
  }

  // Native flavor fills the local Nextcloud credential form (no Keycloak
  // redirect) — but only the administrator persona has a known direct-login
  // password; every other persona (biber, other LDAP users) authenticates
  // through Keycloak or LDAP and must use the Keycloak credential.
  const effectiveUsername = username;
  const effectivePassword =
    nextcloudLoginFlavor === "native" && username === loginUsername
      ? nextcloudDirectLoginPassword
      : password;

  await expect(usernameField).toBeVisible();
  await usernameField.click();
  await usernameField.fill(effectiveUsername);
  await usernameField.press("Tab");
  await passwordField.fill(effectivePassword);
  await signInButton.click();

  const postLoginState = await waitForVisibleCandidate(
    adminPage,
    standaloneShellCandidates,
    60_000,
    "Timed out waiting for a signed-in Nextcloud shell after the login redirect"
  );

  await expect(postLoginState.locator).toBeVisible();
  await dismissBlockingNextcloudModals(adminPage, adminPage);
}

async function logoutStandaloneNextcloud(adminPage) {
  // `#user-menu button` is non-strict on Nextcloud 32+: the menu wrapper
  // wraps both the trigger button (aria-label="Settings menu") AND the
  // submenu's own buttons once it has been opened. Pin to the trigger via
  // its aria-label (stable across templates) and fall back to "first inside
  // #user-menu" only if the role lookup misses (e.g. localized aria-labels).
  const userMenuTrigger = adminPage
    .locator(
      "#user-menu button[aria-label='Settings menu'], #user-menu > button, #user-menu button"
    )
    .first();
  const logoutLinkByName = adminPage.getByRole("link", { name: "Log out" });
  const logoutLinkByHref = adminPage.locator('a[href*="logout"]');
  const logoutConfirmButton = adminPage.getByRole("button", { name: "Logout" });

  await dismissBlockingNextcloudModals(adminPage, adminPage);
  await clickUserMenuWithModalRetry(adminPage, adminPage, userMenuTrigger);

  const logoutLink = await waitForFirstVisible(
    adminPage,
    [logoutLinkByName, logoutLinkByHref],
    15_000
  );
  await expect(logoutLink).toBeVisible();
  await logoutLink.click();

  const logoutConfirmationVisible = await logoutConfirmButton
    .first()
    .waitFor({ state: "visible", timeout: 10_000 })
    .then(() => true)
    .catch(() => false);
  if (logoutConfirmationVisible) {
    await logoutConfirmButton.click();
  }
}

// LDAP-first-login caveat (see roles/web-app-nextcloud/docs/LDAP.md): a fresh
// Nextcloud + LDAP deployment only materializes a user's NC account on first
// successful login, so the very first attempt for a non-administrator persona
// can fail or stall. Retry the full login flow once after a short delay so
// the suite stays deterministic without disabling the first-login behavior.
async function loginToStandaloneNextcloudWithRetry(adminPage, username, password) {
  try {
    await loginToStandaloneNextcloud(adminPage, username, password);
    return;
  } catch {
    await adminPage.waitForTimeout(5_000);
    await loginToStandaloneNextcloud(adminPage, username, password);
  }
}

// Fail fast with a clear message if the rendered `.env` is missing any of
// the values the tests rely on, instead of timing out mid-flow.
function beforeEach() {
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set in the Playwright env file").toBeTruthy();
  expect(nextcloudBaseUrl, "NEXTCLOUD_BASE_URL must be set in the Playwright env file").toBeTruthy();
  expect(loginUsername, "LOGIN_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(loginPassword, "LOGIN_PASSWORD must be set in the Playwright env file").toBeTruthy();
  expect(biberUsername, "BIBER_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set in the Playwright env file").toBeTruthy();
}

module.exports = {
  env: {
    loginUsername,
    loginPassword,
    biberUsername,
    biberPassword,
    nextcloudBaseUrl,
    nextcloudUsernameFieldPattern,
    nextcloudCredentialSubmitPattern,
    nextcloudOidcEnabled,
    nextcloudLdapEnabled,
    nextcloudLoginFlavor,
  },
  getNextcloudShellCandidates,
  waitForFirstVisible,
  waitForVisibleCandidate,
  dismissBlockingNextcloudModals,
  clickUserMenuWithModalRetry,
  loginToStandaloneNextcloud,
  logoutStandaloneNextcloud,
  loginToStandaloneNextcloudWithRetry,
  findFirstVisibleCandidate,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
  beforeEach,
};
