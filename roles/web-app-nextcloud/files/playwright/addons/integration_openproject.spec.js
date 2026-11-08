const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");
const { gotoOnion, performKeycloakLoginForm } = require("../personas");
const { decodeDotenvQuotedValue } = require("../personas/utils/dotenv");

test("integration integration_openproject: two-way OAuth coupling provisioned and connectable to partner OpenProject", async ({ browser }) => {
  skipUnlessAddonEnabled("integration_openproject");
  test.setTimeout(resolveTimeout(120_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    await gotoOnion(page,
      new URL("settings/admin/openproject", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) }
    );
    await shared.dismissBlockingNextcloudModals(page, page);

    const adminSection = page
      .locator("#openproject_prefs, #openproject-server-host, #openproject-prefs")
      .or(page.getByText(/openproject/i))
      .first();
    await expect(
      adminSection,
      "the OpenProject integration admin settings section must render when the addon is enabled"
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    const oauthConfigured = page
      .locator('input[id*="openproject-oauth-client-id"], input[id*="client-id"], input[id*="client-secret"]')
      .or(page.getByText(/reset oauth|replace oauth|nextcloud oauth (client|values)/i))
      .or(page.getByText(/oauth client id|client secret/i))
      .first();
    await expect(
      oauthConfigured,
      "the admin panel must show the provisioned OAuth client (proves the two-way OAuth pair is registered on BOTH sides). When integration_openproject is enabled but this is absent, the coupling failed to provision — the test MUST fail here, not skip."
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    const nextcloudHost = new URL(shared.env.nextcloudBaseUrl).host;
    const adminConfig = page.locator(
      "#initial-state-integration_openproject-admin-settings-config"
    );
    let instanceHost = null;
    let clientId = "";
    let clientSecret = "";
    let authMethod = "";
    if (await adminConfig.count()) {
      const raw =
        (await adminConfig.inputValue().catch(() => "")) ||
        (await adminConfig.getAttribute("value").catch(() => "")) ||
        "";
      let decoded;
      try {
        decoded = Buffer.from(raw, "base64").toString("utf8");
      } catch {
        decoded = raw;
      }
      try {
        const cfg = JSON.parse(decoded);
        const url = cfg.openproject_instance_url || "";
        if (/^https?:\/\//.test(url)) instanceHost = new URL(url).host;
        clientId = cfg.openproject_client_id || "";
        clientSecret = cfg.openproject_client_secret || "";
        authMethod = cfg.authorization_method || "";
      } catch {
        instanceHost = null;
      }
    }
    expect(instanceHost, "the OpenProject instance URL must be configured on the admin panel (integration_openproject openproject_instance_url)").toBeTruthy();
    expect(
      instanceHost,
      "the configured OpenProject instance URL must be the partner host, not the Nextcloud host"
    ).not.toBe(nextcloudHost);

    expect(
      clientId.length,
      "the OpenProject OAuth application client_id must be provisioned on the partner and linked into integration_openproject (the NC->OP half of the two-way OAuth coupling)"
    ).toBeGreaterThan(0);
    expect(
      clientSecret.length,
      "the OpenProject OAuth application client_secret must be linked into integration_openproject (proves the partner registered the OAuth app and returned its secret)"
    ).toBeGreaterThan(0);
    expect(
      authMethod,
      "integration_openproject must be wired for the OAuth2 authorization method once the bidirectional coupling is provisioned"
    ).toBe("oauth2");
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});

const OAUTH_REDIRECT_PATH = "integration_openproject/oauth-redirect";

function connectButton(page) {
  return page.getByRole("button", { name: /connect to openproject|mit openproject verbinden/i }).first();
}

function disconnectButton(page) {
  return page.getByRole("button", { name: /disconnect from openproject|von openproject trennen/i }).first();
}

async function openOpenProjectPersonalSettings(page) {
  await gotoOnion(page,
    new URL("index.php/settings/user/openproject", shared.env.nextcloudBaseUrl).toString(),
    { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) }
  );
  await shared.dismissBlockingNextcloudModals(page, page);
  await expect(
    connectButton(page).or(disconnectButton(page)).first(),
    "the integration_openproject personal settings must offer 'Connect to OpenProject' or 'Disconnect from OpenProject'; anything else means the user-side OAuth configuration (admin_config_ok) is broken"
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
}

async function disconnectFromOpenProjectIfConnected(page) {
  const disconnect = disconnectButton(page);
  if (!(await disconnect.isVisible().catch(() => false))) return;
  await Promise.all([
    page.waitForResponse(
      (response) =>
        response.request().method() === "PUT" &&
        new URL(response.url()).pathname.includes("integration_openproject/config"),
      { timeout: resolveTimeout(30_000) }
    ),
    shared.clickWithModalRetry(page, page, disconnect),
  ]);
  await expect(
    connectButton(page),
    "after 'Disconnect from OpenProject' the personal settings must offer 'Connect to OpenProject' again"
  ).toBeVisible({ timeout: resolveTimeout(30_000) });
}

async function ensureOpenProjectSession(page) {
  const openProjectUrl = decodeDotenvQuotedValue(process.env.OPENPROJECT_BASE_URL || "");
  expect(
    openProjectUrl,
    "OPENPROJECT_BASE_URL must name the partner OpenProject while integration_openproject is enabled"
  ).not.toBe("");
  const openProjectHost = new URL(openProjectUrl).host;
  const loginForm = page
    .locator("form")
    .filter({ has: page.locator("input[type='password']:visible") })
    .first();
  await gotoOnion(page, openProjectUrl, { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) });
  const deadline = Date.now() + resolveTimeout(90_000);
  while (Date.now() < deadline) {
    const current = new URL(page.url());
    if (current.host === openProjectHost && !/login|two_factor|oauth2\/callback/.test(current.pathname)) {
      return;
    }
    if (await loginForm.isVisible().catch(() => false)) {
      await performKeycloakLoginForm(loginForm, shared.env.loginUsername, shared.env.loginPassword);
    }
    await page.waitForTimeout(resolveTimeout(500));
  }
  const stoppedAt = new URL(page.url());
  throw new Error(`no OpenProject session after the SSO login; the browser stopped at ${stoppedAt.host}${stoppedAt.pathname}`);
}

async function authorizeOnOpenProject(page, oauthRedirectReached) {
  const loginForm = page
    .locator("form")
    .filter({ has: page.locator("input[type='password']:visible") })
    .first();
  const authorizeButton = page
    .locator("form[action*='/oauth/authorize']:not(:has(input[name='_method'])) [type='submit']")
    .or(page.getByRole("button", { name: /^\s*(authori[sz]e|autorisieren)\s*$/i }))
    .first();
  const deadline = Date.now() + resolveTimeout(120_000);
  let loginSubmitted = false;

  while (!oauthRedirectReached() && Date.now() < deadline) {
    if (await authorizeButton.isVisible().catch(() => false)) {
      await authorizeButton.click({ timeout: resolveTimeout(30_000) });
      return;
    }
    if (!loginSubmitted && (await loginForm.isVisible().catch(() => false))) {
      await performKeycloakLoginForm(loginForm, shared.env.loginUsername, shared.env.loginPassword);
      loginSubmitted = true;
    }
    await page.waitForTimeout(resolveTimeout(500));
  }
}

test("integration integration_openproject: a user connects to OpenProject via OAuth and Nextcloud redeems the code at /oauth/token", async ({ browser }) => {
  skipUnlessAddonEnabled("integration_openproject");
  test.setTimeout(resolveTimeout(300_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  let connectStarted = false;

  try {
    await shared.loginToStandaloneNextcloud(page);
    await ensureOpenProjectSession(page);
    await openOpenProjectPersonalSettings(page);
    await disconnectFromOpenProjectIfConnected(page);

    const connect = connectButton(page);
    await expect(
      connect,
      "the 'Connect to OpenProject' control must render for an unconnected user once the OAuth client is provisioned"
    ).toBeVisible({ timeout: resolveTimeout(30_000) });

    let oauthRedirectReached = false;
    const oauthRedirect = page
      .waitForResponse(
        (response) => new URL(response.url()).pathname.includes(OAUTH_REDIRECT_PATH),
        { timeout: resolveTimeout(180_000) }
      )
      .then(
        (response) => {
          oauthRedirectReached = true;
          return { response };
        },
        (error) => {
          oauthRedirectReached = true;
          return { error };
        }
      );

    connectStarted = true;
    await shared.clickWithModalRetry(page, page, connect);
    await authorizeOnOpenProject(page, () => oauthRedirectReached);

    const { response, error } = await oauthRedirect;
    const stoppedAt = new URL(page.url());
    expect(
      error,
      `the OpenProject OAuth round trip must return the browser to Nextcloud's ${OAUTH_REDIRECT_PATH}; it stopped at ${stoppedAt.host}${stoppedAt.pathname}`
    ).toBeUndefined();
    const status = response.status();
    expect(
      status,
      `Nextcloud's ${OAUTH_REDIRECT_PATH} answered HTTP ${status}: redeeming the authorization code at OpenProject's /oauth/token failed (e.g. a trailing slash in openproject_instance_url makes the app request //oauth/token)`
    ).toBeLessThan(500);

    await page.waitForURL(/\/settings\/user\/openproject/, {
      waitUntil: "domcontentloaded",
      timeout: resolveTimeout(60_000),
    });
    await shared.dismissBlockingNextcloudModals(page, page);
    await expect(
      page.getByText(/connected as|verbunden als/i).first(),
      "after the OAuth round trip the personal settings must show 'Connected as <OpenProject user>'; without it Nextcloud stored no usable OpenProject access token"
    ).toBeVisible({ timeout: resolveTimeout(60_000) });
    await expect(
      disconnectButton(page),
      "a connected user must be offered 'Disconnect from OpenProject'"
    ).toBeVisible({ timeout: resolveTimeout(30_000) });
  } finally {
    if (connectStarted) {
      await openOpenProjectPersonalSettings(page)
        .then(() => disconnectFromOpenProjectIfConnected(page))
        .catch(() => {});
    }
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
