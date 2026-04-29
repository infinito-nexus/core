// End-to-end tests for the Nextcloud role.
//
// Two scenarios:
//   1. "nextcloud talk admin settings" — SSO-login as admin, navigate to the
//      Talk admin page, and assert the configured HPB / STUN / TURN values
//      are rendered (and that legacy onboard values are absent).
//   2. "dashboard to nextcloud login"  — enter Nextcloud through the
//      portal dashboard iframe, complete the OIDC handoff via Keycloak,
//      reuse the authenticated context for the Talk check, then log out.
//
// All authentication goes through Keycloak (OIDC). Local Nextcloud login
// is intentionally NOT exercised: `oidc_login_hide_password_form` keeps the
// native form hidden in this deployment.
const { test, expect } = require("@playwright/test");

// `ignoreHTTPSErrors` is needed because the local stack typically uses the
// self-signed CA set up by `make trust-ca`, which the Playwright container
// does not trust by default.
test.use({
  ignoreHTTPSErrors: true
});

// ---------------------------------------------------------------------------
// Env decoding
// ---------------------------------------------------------------------------

function decodeDotenvQuotedValue(value) {
  if (typeof value !== "string" || value.length < 2) {
    return value;
  }

  if (!(value.startsWith('"') && value.endsWith('"'))) {
    return value;
  }

  const encoded = value.slice(1, -1);

  try {
    return JSON.parse(`"${encoded}"`).replace(/\$\$/g, "$");
  } catch {
    return encoded.replace(/\$\$/g, "$");
  }
}

// `docker --env-file` preserves the quotes emitted by `dotenv_quote`,
// so normalize these values before building URLs or typing credentials.
// ---------------------------------------------------------------------------
// Env-driven config
//
// All values originate from the rendered `.env` under the staging dir. The
// Talk-related values are optional and gate the first test via
// `nextcloudTalkSettingsCheckEnabled`.
// ---------------------------------------------------------------------------
const loginUsername = decodeDotenvQuotedValue(process.env.LOGIN_USERNAME);
const loginPassword = decodeDotenvQuotedValue(process.env.LOGIN_PASSWORD);
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const nextcloudDirectLoginPassword = decodeDotenvQuotedValue(process.env.NEXTCLOUD_DIRECT_LOGIN_PASSWORD) || loginPassword;
const oidcIssuerUrl = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL);
const nextcloudBaseUrl = decodeDotenvQuotedValue(process.env.NEXTCLOUD_BASE_URL);
const nextcloudTalkSettingsCheckEnabled = decodeDotenvQuotedValue(process.env.NEXTCLOUD_TALK_SETTINGS_CHECK_ENABLED) === "true";
const nextcloudTalkSettingsUrl = decodeDotenvQuotedValue(process.env.NEXTCLOUD_TALK_SETTINGS_URL);
const nextcloudTalkExpectedSignalingUrl = decodeDotenvQuotedValue(process.env.NEXTCLOUD_TALK_EXPECTED_SIGNALING_URL);
const nextcloudTalkExpectedStunServer = decodeDotenvQuotedValue(process.env.NEXTCLOUD_TALK_EXPECTED_STUN_SERVER);
const nextcloudTalkExpectedTurnServer = decodeDotenvQuotedValue(process.env.NEXTCLOUD_TALK_EXPECTED_TURN_SERVER);
const nextcloudTalkUnexpectedStunServer = decodeDotenvQuotedValue(process.env.NEXTCLOUD_TALK_UNEXPECTED_STUN_SERVER);
const nextcloudTalkUnexpectedTurnServer = decodeDotenvQuotedValue(process.env.NEXTCLOUD_TALK_UNEXPECTED_TURN_SERVER);
const nextcloudUsernameFieldPattern = /account name or email|username or email/i;
const nextcloudCredentialSubmitPattern = /sign in|log in/i;

// Condition variables driving the login flavor. Ansible renders these from the
// role's services.{oidc,ldap}.enabled (meta/services.yml) so the spec never has to
// sniff which login UI shape the deployment exposes:
//   - OIDC + LDAP  -> "oidc_login"  (pulsejet/nextcloud-oidc-login,
//                                    auto_redirect hands straight to Keycloak)
//   - OIDC only    -> "sociallogin" (nextcloud/sociallogin shows a
//                                    "Log in with Keycloak" entry first)
//   - no OIDC      -> "native"      (no Keycloak handoff; NC credential form)
const nextcloudOidcEnabled =
  (process.env.NEXTCLOUD_OIDC_ENABLED || "true").toLowerCase() === "true";
const nextcloudLdapEnabled =
  (process.env.NEXTCLOUD_LDAP_ENABLED || "false").toLowerCase() === "true";
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

async function findFirstVisibleCandidate(candidates) {
  for (const candidate of candidates) {
    const locator = candidate.locator.first();

    if (await locator.isVisible().catch(() => false)) {
      return { ...candidate, locator };
    }
  }

  return null;
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
// Settings-page assertions
//
// Talk admin settings are partly rendered as plain text and partly as
// `<input value="...">` fields. `innerText()` alone would miss the input
// values, so collect both text and form values before asserting presence or
// absence of configured / legacy endpoints.
// ---------------------------------------------------------------------------

async function collectNextcloudSettingsText(target) {
  const bodyText = await target.locator("body").innerText().catch(() => "");
  const formValues = await target.locator("input, textarea, select").evaluateAll((elements) => {
    return elements.flatMap((element) => {
      const values = [];
      const value = typeof element.value === "string" ? element.value.trim() : "";
      const text = typeof element.textContent === "string" ? element.textContent.trim() : "";

      if (value) {
        values.push(value);
      }

      if (text) {
        values.push(text);
      }

      return values;
    });
  }).catch(() => []);

  return [bodyText, ...formValues].filter(Boolean).join("\n");
}

async function expectNextcloudSettingValue(page, expectedValue, label) {
  await expect
    .poll(
      async () => collectNextcloudSettingsText(page),
      {
        timeout: 30_000,
        message: `Expected ${label} to be visible in the Nextcloud Talk admin settings: ${expectedValue}`
      }
    )
    .toContain(expectedValue);
}

async function expectNextcloudSettingAbsent(page, unexpectedValue, label) {
  await expect
    .poll(
      async () => collectNextcloudSettingsText(page),
      {
        timeout: 30_000,
        message: `Expected ${label} to stay absent in the Nextcloud Talk admin settings: ${unexpectedValue}`
      }
    )
    .not.toContain(unexpectedValue);
}

// ---------------------------------------------------------------------------
// Social-login entry points
//
// Some NC login layouts show an explicit "Log in with <provider>" button
// before the credential form. Detect it so the dashboard flow can click
// through to the Keycloak form regardless of which variant renders.
// ---------------------------------------------------------------------------

function getNextcloudSocialLoginCandidates(target) {
  return [
    {
      kind: "social-login",
      locator: target.locator(
        'a[href*="/apps/sociallogin/"], a[href*="/custom_oidc/"], button[formaction*="/apps/sociallogin/"], button[formaction*="/custom_oidc/"]'
      )
    },
    {
      kind: "social-login",
      locator: target.getByRole("link", { name: /log in with|sign in with|continue with/i })
    },
    {
      kind: "social-login",
      locator: target.getByRole("button", { name: /log in with|sign in with|continue with/i })
    }
  ];
}

async function enterNextcloudLoginThroughVisibleEntryPoint(page, target, usernameField, signInButton, contextLabel) {
  const initialState = await waitForVisibleCandidate(
    page,
    [
      { kind: "credentials", locator: usernameField },
      { kind: "credentials", locator: signInButton },
      ...getNextcloudSocialLoginCandidates(target)
    ],
    60_000,
    `Timed out waiting for the ${contextLabel} login entry point`
  );

  if (initialState.kind === "social-login") {
    await initialState.locator.click({ timeout: 5_000 });

    await waitForVisibleCandidate(
      page,
      [
        { kind: "credentials", locator: usernameField },
        { kind: "credentials", locator: signInButton }
      ],
      60_000,
      `Timed out waiting for the ${contextLabel} identity-provider login form after following the social-login entry point`
    );
  }
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
      flavorCandidates = [...credentialCandidates, ...standaloneShellCandidates];
      timeoutMessage =
        "Timed out waiting for the Keycloak login form or an already-authenticated Nextcloud shell";
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
  const userMenuTrigger = adminPage.locator("#user-menu button");
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
  } catch (error) {
    await adminPage.waitForTimeout(5_000);
    await loginToStandaloneNextcloud(adminPage, username, password);
  }
}

// ---------------------------------------------------------------------------
// Talk admin verification
//
// Open a fresh page in the given context, SSO-login, navigate to the Talk
// admin settings URL, and assert the deployed HPB / STUN / TURN values are
// present while the known legacy onboard values are absent. Then click every
// "Test server" / "Test this server" button and fail if any of the known
// spreed error strings show up (Cannot connect, No working ICE, etc.).
// ---------------------------------------------------------------------------

// Error strings emitted by the spreed admin UI when a signaling / STUN / TURN
// test button reports a failure. Kept in one place so the list stays easy to
// audit against the spreed source.
const talkTestServerErrorPatterns = [
  /Error:\s*Cannot connect to server/i,
  /Error:\s*No working ICE candidates returned by the TURN server/i,
  /Error:\s*Server seems to be a Signaling server/i,
  /Testing server seems to be broken/i
];

// Positive success markers emitted by the spreed admin UI. The HPB signaling
// server and the recording backend both auto-run their reachability check on
// mount (HTTPS/WebSocket handshake) and render "OK: Running version: X" once
// it succeeds. TURN/STUN require WebRTC-level UDP connectivity from the
// browser to the coturn host, which is not guaranteed from a Playwright
// container in a separate docker network, so those are only covered by the
// error-absence assertion below, not by a positive marker here. The
// "OK: Running version:" pattern is expected to appear at least twice
// (signaling + recording) on a fully configured stack.
const talkTestServerRequiredSuccessPatterns = [
  {
    label: "HPB signaling and recording backend versions",
    pattern: /OK:\s*Running version:\s*\S+[\s\S]*?OK:\s*Running version:\s*\S+/i
  }
];

async function clickAllTalkTestServerButtonsAndVerify(page) {
  // Spreed labels its signaling-server button "Test server" and the
  // STUN/TURN entries "Test this server". Match both.
  const testButtons = page.getByRole("button", { name: /^test( this)? server$/i });
  const total = await testButtons.count();

  const clicked = [];
  for (let i = 0; i < total; i += 1) {
    const button = testButtons.nth(i);
    if (!(await button.isVisible().catch(() => false))) {
      continue;
    }
    await button.scrollIntoViewIfNeeded().catch(() => {});
    await button.click({ timeout: 5_000 }).catch(() => {});
    clicked.push(i);
  }

  expect(
    clicked.length,
    "Expected at least one Talk 'Test server' / 'Test this server' button on the admin page"
  ).toBeGreaterThan(0);

  // Poll until every required success marker has rendered somewhere in the
  // Talk admin panel. `page.evaluate(() => document.body.innerText)` is used
  // instead of `page.locator("body").innerText()` because the latter triggers
  // visibility checks that return empty on this admin layout.
  const readBodyText = async () =>
    page.evaluate(() => document.body ? document.body.innerText : "").catch(() => "");

  for (const { label, pattern } of talkTestServerRequiredSuccessPatterns) {
    await expect
      .poll(readBodyText, {
        timeout: 30_000,
        message: `Expected Talk admin page to report ${label} test success after clicking its Test button`
      })
      .toMatch(pattern);
  }

  const bodyText = await readBodyText();
  for (const pattern of talkTestServerErrorPatterns) {
    expect(
      bodyText,
      `Talk admin page reported an error after clicking the Test server buttons (pattern ${pattern})`
    ).not.toMatch(pattern);
  }
}

async function verifyNextcloudTalkAdminSettings(browserContext) {
  if (!nextcloudTalkSettingsCheckEnabled) {
    return;
  }

  const expectedTalkSettingsUrl = new URL(nextcloudTalkSettingsUrl);
  const adminPage = await browserContext.newPage();

  try {
    await loginToStandaloneNextcloud(adminPage);
    await adminPage.goto(nextcloudTalkSettingsUrl, {
      waitUntil: "domcontentloaded",
      timeout: 60_000
    });
    await expect
      .poll(
        async () => {
          const currentUrl = new URL(adminPage.url());

          return {
            pathname: currentUrl.pathname,
            search: currentUrl.search
          };
        },
        {
          timeout: 30_000,
          message: `Expected Nextcloud admin Talk settings page to load: ${nextcloudTalkSettingsUrl}`
        }
      )
      .toMatchObject({
        pathname: expectedTalkSettingsUrl.pathname,
        search: expectedTalkSettingsUrl.search
      });

    await dismissBlockingNextcloudModals(adminPage, adminPage);
    await expectNextcloudSettingValue(adminPage, nextcloudTalkExpectedSignalingUrl, "Talk signaling URL");
    await expectNextcloudSettingValue(adminPage, nextcloudTalkExpectedStunServer, "Talk STUN server");
    await expectNextcloudSettingValue(adminPage, nextcloudTalkExpectedTurnServer, "Talk TURN server");

    if (nextcloudTalkUnexpectedStunServer) {
      await expectNextcloudSettingAbsent(adminPage, nextcloudTalkUnexpectedStunServer, "legacy Talk STUN server");
    }

    if (nextcloudTalkUnexpectedTurnServer) {
      await expectNextcloudSettingAbsent(adminPage, nextcloudTalkUnexpectedTurnServer, "legacy Talk TURN server");
    }

    await clickAllTalkTestServerButtonsAndVerify(adminPage);
  } finally {
    await adminPage.close().catch(() => {});
  }
}

// ---------------------------------------------------------------------------
// Test cases
// ---------------------------------------------------------------------------

// Fail fast with a clear message if the rendered `.env` is missing any of
// the values the tests rely on, instead of timing out mid-flow.
test.beforeEach(() => {
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set in the Playwright env file").toBeTruthy();
  expect(nextcloudBaseUrl, "NEXTCLOUD_BASE_URL must be set in the Playwright env file").toBeTruthy();
  expect(loginUsername, "LOGIN_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(loginPassword, "LOGIN_PASSWORD must be set in the Playwright env file").toBeTruthy();
  expect(biberUsername, "BIBER_USERNAME must be set in the Playwright env file").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set in the Playwright env file").toBeTruthy();

  if (nextcloudTalkSettingsCheckEnabled) {
    expect(nextcloudTalkSettingsUrl, "NEXTCLOUD_TALK_SETTINGS_URL must be set when Talk admin checks are enabled").toBeTruthy();
    expect(nextcloudTalkExpectedSignalingUrl, "NEXTCLOUD_TALK_EXPECTED_SIGNALING_URL must be set when Talk admin checks are enabled").toBeTruthy();
    expect(nextcloudTalkExpectedStunServer, "NEXTCLOUD_TALK_EXPECTED_STUN_SERVER must be set when Talk admin checks are enabled").toBeTruthy();
    expect(nextcloudTalkExpectedTurnServer, "NEXTCLOUD_TALK_EXPECTED_TURN_SERVER must be set when Talk admin checks are enabled").toBeTruthy();
  }
});

test("nextcloud talk admin settings", async ({ browser }) => {
  test.skip(!nextcloudTalkSettingsCheckEnabled, "Talk admin checks are disabled in the current Playwright env");

  const browserContext = await browser.newContext({
    ignoreHTTPSErrors: true
  });

  try {
    await verifyNextcloudTalkAdminSettings(browserContext);
  } finally {
    await browserContext.close().catch(() => {});
  }
});

test("dashboard to nextcloud login", async ({ page }) => {
  const expectedOidcAuthUrl = `${oidcIssuerUrl.replace(/\/$/, "")}/protocol/openid-connect/auth`;
  const expectedNextcloudBaseUrl = nextcloudBaseUrl.replace(/\/$/, "");

  const dashboardLoaded = await page.goto("/", {
    waitUntil: "domcontentloaded",
    timeout: 30_000
  }).then(() => true).catch(() => false);

  test.skip(!dashboardLoaded, "Dashboard is not reachable in the current local setup");
  await page.getByRole("link", { name: "Explore Nextcloud" }).click();

  const nextcloudIframe = page.locator("#main iframe");
  const nextcloudFrame = nextcloudIframe.contentFrame();
  const usernameField = nextcloudFrame.getByRole("textbox", { name: nextcloudUsernameFieldPattern });
  const passwordField = nextcloudFrame.getByRole("textbox", { name: "Password" });
  const rememberMeCheckbox = nextcloudFrame.getByRole("checkbox", { name: "Remember me" });
  const signInButton = nextcloudFrame.getByRole("button", { name: nextcloudCredentialSubmitPattern });
  const userMenuTriggerInMount = nextcloudFrame.locator("#user-menu button");
  const logoutLinkByName = nextcloudFrame.getByRole("link", { name: "Log out" });
  const logoutLinkByHref = nextcloudFrame.locator('a[href*="logout"]');
  const logoutConfirmButton = nextcloudFrame.getByRole("button", { name: "Logout" });
  const userMenuCandidates = [
    { kind: "user-menu", locator: userMenuTriggerInMount }
  ];
  const postLoginCandidates = [
    ...userMenuCandidates,
    ...getNextcloudShellCandidates(nextcloudFrame)
  ];

  await expect(nextcloudIframe).toBeVisible();
  await expect
    .poll(
      async () => {
        const iframeHandle = await nextcloudIframe.elementHandle();
        const iframeFrame = iframeHandle ? await iframeHandle.contentFrame() : null;
        const currentUrl = iframeFrame ? iframeFrame.url() : "";
        return currentUrl.includes(expectedOidcAuthUrl) || currentUrl.startsWith(expectedNextcloudBaseUrl);
      },
      {
        timeout: 60_000,
        message: `Expected Nextcloud iframe to load either the Keycloak OIDC login or the standalone Nextcloud login page`
      }
    )
    .toBe(true);

  await enterNextcloudLoginThroughVisibleEntryPoint(
    page,
    nextcloudFrame,
    usernameField,
    signInButton,
    "dashboard-embedded Nextcloud"
  );

  await expect(usernameField).toBeVisible();
  await usernameField.click();
  await usernameField.fill(loginUsername);
  await usernameField.press("Tab");
  await passwordField.fill(loginPassword);

  if (await rememberMeCheckbox.first().isVisible().catch(() => false)) {
    await rememberMeCheckbox.check();
  } else {
    await nextcloudFrame.getByText("Remember me").click({ timeout: 2_000 }).catch(() => {});
  }

  await signInButton.click();
  await expect
    .poll(
      async () => {
        const iframeHandle = await nextcloudIframe.elementHandle();
        const iframeFrame = iframeHandle ? await iframeHandle.contentFrame() : null;

        return iframeFrame ? iframeFrame.url() : "";
      },
      {
        timeout: 60_000,
        message: `Expected Nextcloud iframe to redirect back to Nextcloud after Keycloak login: ${expectedNextcloudBaseUrl}`
      }
    )
    .toContain(expectedNextcloudBaseUrl);

  const postLoginState = await waitForVisibleCandidate(
    page,
    postLoginCandidates,
    60_000,
    "Timed out waiting for a signed-in Nextcloud shell after the Keycloak login redirect"
  );

  await expect(postLoginState.locator).toBeVisible();

  // First login can show one or more stacked onboarding dialogs that block clicks.
  await dismissBlockingNextcloudModals(page, nextcloudFrame);

  await verifyNextcloudTalkAdminSettings(page.context());

  // Embedded Nextcloud layouts can hide the user menu even when the login succeeded.
  const userMenuState = postLoginState.kind === "user-menu"
    ? postLoginState
    : await waitForVisibleCandidate(page, userMenuCandidates, 10_000).catch(() => null);

  if (!userMenuState) {
    await page.goto("/");
    return;
  }

  await clickUserMenuWithModalRetry(page, nextcloudFrame, userMenuState.locator);

  const logoutLink = await waitForFirstVisible(
    page,
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

  await page.goto("/");
});

test("biber logs into nextcloud via OIDC and logs out", async ({ browser }) => {
  const biberContext = await browser.newContext({ ignoreHTTPSErrors: true });
  const biberPage = await biberContext.newPage();

  try {
    await loginToStandaloneNextcloudWithRetry(biberPage, biberUsername, biberPassword);

    const shellState = await waitForVisibleCandidate(
      biberPage,
      getNextcloudShellCandidates(biberPage),
      60_000,
      "Timed out waiting for a signed-in Nextcloud shell for biber"
    );
    await expect(shellState.locator).toBeVisible();

    await logoutStandaloneNextcloud(biberPage);

    const loginUrl = new URL("login", nextcloudBaseUrl).toString();
    await biberPage.goto(loginUrl, { waitUntil: "domcontentloaded", timeout: 60_000 }).catch(() => {});
    const shellAfterLogout = await findFirstVisibleCandidate(getNextcloudShellCandidates(biberPage));
    expect(
      shellAfterLogout,
      "Expected biber to be logged out after clicking Log out (no authenticated Nextcloud shell on /login)"
    ).toBeNull();
  } finally {
    await biberPage.close().catch(() => {});
    await biberContext.close().catch(() => {});
  }
});
