const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { decodeDotenvQuotedValue, normalizeBaseUrl, performKeycloakLoginForm, gotoOnion } = require("./personas");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");

const env = {
  appBaseUrl: normalizeBaseUrl(decodeDotenvQuotedValue(process.env.APP_BASE_URL)),
  canonicalDomain: decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN),
  oidcIssuerUrl: normalizeBaseUrl(decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL || "")),
  adminUsername: decodeDotenvQuotedValue(process.env.ADMIN_USERNAME),
  adminPassword: decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD),
  adminEmail: decodeDotenvQuotedValue(process.env.ADMIN_EMAIL),
  biberUsername: decodeDotenvQuotedValue(process.env.BIBER_USERNAME),
  biberPassword: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD),
  breakglassEmail: decodeDotenvQuotedValue(process.env.BREAKGLASS_EMAIL),
  breakglassPassword: decodeDotenvQuotedValue(process.env.BREAKGLASS_PASSWORD),
  mastodonBaseUrl: normalizeBaseUrl(decodeDotenvQuotedValue(process.env.MASTODON_BASE_URL || "")),
  pixelfedBaseUrl: normalizeBaseUrl(decodeDotenvQuotedValue(process.env.PIXELFED_BASE_URL || "")),
  linkedinFakeUrl: normalizeBaseUrl(decodeDotenvQuotedValue(process.env.LINKEDIN_FAKE_URL || "")),
  organisationWorkspace: decodeDotenvQuotedValue(process.env.ORGANISATION_WORKSPACE),
  oidcEnabled: isServiceEnabled("sso"),
};

const SAMPLE_PNG = Buffer.from(
  "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",
  "base64",
);

const LOGIN_PATH = "/login";

function onLoginPage(page) {
  return new URL(page.url()).pathname.startsWith(LOGIN_PATH);
}

async function gotoLogin(page) {
  return gotoOnion(page, `${env.appBaseUrl}${LOGIN_PATH}`, { waitUntil: "domcontentloaded" });
}

function profileMenuTrigger(page) {
  return page.locator('[data-testid="profile-menu-trigger"]').first();
}

async function assertAuthenticated(page, label) {
  await expect
    .poll(() => onLoginPage(page), {
      timeout: resolveTimeout(60_000),
      message: `${label}: expected to leave the OpenPost login page`,
    })
    .toBe(false);
  const onboarding = page.getByRole("heading", { name: /create your first workspace/i });
  await expect(
    profileMenuTrigger(page).or(onboarding),
    `${label}: the authenticated OpenPost desk or its first-run onboarding must render`,
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
  if (await onboarding.isVisible()) {
    await page.getByLabel(/workspace name/i).fill(`${label} workspace`);
    await page.getByRole("button", { name: /create workspace/i }).click();
  }
  await expect(
    profileMenuTrigger(page),
    `${label}: the authenticated OpenPost profile menu must be visible`,
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
}

async function signInViaLocal(page, email, password, label) {
  await gotoLogin(page);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  await page.locator("form").filter({ has: page.locator("#password") }).locator('button[type="submit"]').click();
  await assertAuthenticated(page, label);
}

function oidcProviderButton(page) {
  return page.locator("a, button").filter({ hasText: /sso|single sign-on|keycloak/i }).first();
}

async function signInViaOidc(page, username, password, label) {
  await gotoLogin(page);
  const button = oidcProviderButton(page);
  await expect(button, `${label}: the Keycloak sign-in button must render on the OpenPost login page`).toBeVisible({
    timeout: resolveTimeout(30_000),
  });
  await button.click();
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `${label}: expected redirect to Keycloak (${env.oidcIssuerUrl}/protocol/openid-connect/auth)`,
    })
    .toContain(`${env.oidcIssuerUrl}/protocol/openid-connect/auth`);
  await performKeycloakLoginForm(page, username, password);
  await assertAuthenticated(page, label);
}

async function logout(page, label) {
  await profileMenuTrigger(page).click();
  await page.getByRole("menuitem", { name: /log\s*out|sign\s*out/i }).click();
  await expect
    .poll(() => onLoginPage(page), {
      timeout: resolveTimeout(60_000),
      message: `${label}: expected logged-out landing on the OpenPost login page`,
    })
    .toBe(true);
}

async function openUsersPanel(page) {
  await gotoOnion(page, `${env.appBaseUrl}/settings?tab=users`, { waitUntil: "domcontentloaded" });
  await expect(page.locator('[data-testid="settings-navigation"]')).toBeVisible({ timeout: resolveTimeout(60_000) });
}

async function openInstanceAdministration(page, label) {
  await openUsersPanel(page);
  await expect(
    page.locator('[data-testid="instance-user-directory"]'),
    `${label}: the instance user directory must render for an instance admin`,
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
  await expect(
    page.locator('[data-testid="instance-user-directory"]').getByText(env.breakglassEmail).first(),
    `${label}: the instance user directory must list the break-glass admin`,
  ).toBeVisible({ timeout: resolveTimeout(30_000) });
}

async function assertInstanceAdministrationDenied(page, label) {
  await openUsersPanel(page);
  await expect(
    page.locator('[data-testid="instance-admin-users"]'),
    `${label}: the instance user directory must stay hidden from a regular user`,
  ).toHaveCount(0);
  await expect(
    page.locator('[data-testid="settings-navigation"]').getByText(/^instance$/i),
    `${label}: the settings navigation must not offer the instance section`,
  ).toHaveCount(0);
}

async function openComposer(page, label) {
  await page.locator('[data-testid="sidebar-new-post"]').click();
  await expect(
    page.locator('[contenteditable="true"], textarea').first(),
    `${label}: the composer must open with an editable text area`,
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
}

async function assertWorkspaceHidden(page, workspaceName, label) {
  expect(workspaceName, "ORGANISATION_WORKSPACE must be set").toBeTruthy();
  await gotoOnion(page, `${env.appBaseUrl}/`, { waitUntil: "domcontentloaded" });
  await page.locator('[data-testid="workspace-menu-trigger"]').click();
  const menu = page.getByRole("menu");
  await expect(menu, `${label}: the workspace switcher must open`).toBeVisible({ timeout: resolveTimeout(30_000) });
  await expect(
    menu.getByText(workspaceName, { exact: true }),
    `${label}: the organisation workspace "${workspaceName}" must not be offered`,
  ).toHaveCount(0);
  await page.keyboard.press("Escape");
}

function crc32(buffer) {
  let crc = 0xffffffff;
  for (const byte of buffer) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function uniquePng(text) {
  const data = Buffer.concat([Buffer.from("Comment\0", "latin1"), Buffer.from(text, "latin1")]);
  const type = Buffer.from("tEXt", "latin1");
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const checksum = Buffer.alloc(4);
  checksum.writeUInt32BE(crc32(Buffer.concat([type, data])));
  const iend = SAMPLE_PNG.length - 12;
  return Buffer.concat([SAMPLE_PNG.subarray(0, iend), length, type, data, checksum, SAMPLE_PNG.subarray(iend)]);
}

async function uploadMedia(page, fileName, label) {
  await gotoOnion(page, `${env.appBaseUrl}/media`, { waitUntil: "domcontentloaded" });
  const addMedia = page.getByRole("button", { name: /add media/i });
  await expect(addMedia, `${label}: the media library must offer "Add media"`).toBeVisible({
    timeout: resolveTimeout(60_000),
  });
  await addMedia.click();
  const dialog = page.getByRole("dialog", { name: /upload media/i });
  await expect(dialog, `${label}: the upload dialog must open`).toBeVisible({ timeout: resolveTimeout(30_000) });
  const completed = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      /\/api\/v1\/media\/upload-session\/[^/]+\/complete$/.test(new URL(response.url()).pathname),
    { timeout: resolveTimeout(60_000) },
  );
  await dialog.locator('input[type="file"]').first().setInputFiles({
    name: fileName,
    mimeType: "image/png",
    buffer: uniquePng(fileName),
  });
  const confirm = dialog.getByRole("button", { name: /^(upload|add|save)/i });
  if (await confirm.first().isVisible().catch(() => false)) {
    await confirm.first().click();
  }
  expect((await completed).ok(), `${label}: OpenPost must complete the upload`).toBe(true);
  await expect(
    dialog.getByText(fileName).first(),
    `${label}: the upload dialog must list the file it received`,
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
  if (await dialog.isVisible().catch(() => false)) {
    await page.keyboard.press("Escape");
  }
  await expect(dialog, `${label}: the upload dialog must close`).toBeHidden({ timeout: resolveTimeout(30_000) });
  await gotoOnion(page, `${env.appBaseUrl}/media`, { waitUntil: "domcontentloaded" });
  await expect(
    page.getByText(fileName).or(page.locator(`img[alt*="${fileName}"]`)).first(),
    `${label}: the uploaded file must appear in the media library`,
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
}

async function openMastodonConnectDialog(page, label) {
  await gotoOnion(page, `${env.appBaseUrl}/settings?tab=accounts`, { waitUntil: "domcontentloaded" });
  const card = page.locator('[data-testid="provider-card-mastodon"]');
  await expect(card, `${label}: the Mastodon provider card must render`).toBeVisible({ timeout: resolveTimeout(60_000) });
  await card.getByRole("button", { name: /^connect$/i }).click();
  const dialog = page.getByRole("dialog", { name: /connect mastodon/i });
  await dialog.getByRole("button", { name: /continue to mastodon/i }).click();
  await dialog.getByRole("textbox", { name: /server address/i }).fill(env.mastodonBaseUrl);
  return dialog;
}

function mastodonChannelActions(page, account) {
  return page.getByRole("button", { name: new RegExp(`^actions for ${account.handle} · mastodon$`, "i") });
}

function skipOnOnionSibling(platform) {
  test.skip(
    env[`${platform}BaseUrl`].includes(".onion"),
    `OpenPost cannot connect an onion ${platform} instance: its Go resolver refuses .onion names`,
  );
}

async function disconnectAccount(page, account) {
  await gotoOnion(page, `${env.appBaseUrl}/settings?tab=accounts`, { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: /connected channels/i })).toBeVisible({ timeout: resolveTimeout(60_000) });
  const actions = mastodonChannelActions(page, account);
  if (!(await actions.isVisible())) {
    return;
  }
  await actions.click();
  await page.getByRole("menuitem", { name: /remove connection/i }).click();
  const confirm = page.getByRole("alertdialog").or(page.getByRole("dialog")).first();
  await expect(confirm, `${account.handle}: OpenPost must ask before removing the connection`).toBeVisible({
    timeout: resolveTimeout(30_000),
  });
  await confirm.getByRole("button", { name: /^remove connection$/i }).click();
  await expect(actions, `${account.handle} must disappear from the connected channels`).toBeHidden({
    timeout: resolveTimeout(60_000),
  });
}

async function connectMastodonAccount(page, context, label) {
  const account = { handle: `@${env.adminUsername}` };
  await disconnectAccount(page, account);
  const dialog = await openMastodonConnectDialog(page, label);
  await dialog.getByRole("button", { name: /^connect$/i }).click();
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: `${label}: expected Mastodon's sign-in page` })
    .toContain(`${env.mastodonBaseUrl}/auth/sign_in`);
  await page.getByRole("link", { name: /sso|single sign-on/i }).click();
  await page.waitForLoadState("domcontentloaded");
  if (page.url().includes(`${env.oidcIssuerUrl}/protocol/openid-connect/auth`)) {
    await performKeycloakLoginForm(page, env.adminUsername, env.adminPassword);
  }
  const authorize = page.getByRole("button", { name: /^authorize$/i });
  await expect
    .poll(async () => page.url().includes("/oauth/authorize/native") || (await authorize.isVisible()), {
      timeout: resolveTimeout(60_000),
      message: `${label}: expected Mastodon's consent screen or its authorization code page`,
    })
    .toBe(true);
  if (await authorize.isVisible()) {
    await authorize.click();
  }
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: `${label}: expected Mastodon's authorization code page` })
    .toContain(`${env.mastodonBaseUrl}/oauth/authorize/native`);
  const code = await page.getByRole("textbox").first().inputValue();
  expect(code, `${label}: Mastodon must show an authorization code`).toBeTruthy();

  const codeDialog = await openMastodonConnectDialog(page, label);
  await codeDialog.getByRole("button", { name: /^code$/i }).click();
  await page.getByRole("textbox", { name: /authorization code/i }).fill(code);
  await page.getByRole("button", { name: /connect account/i }).click();
  await expect
    .poll(() => new URL(page.url()).pathname, {
      timeout: resolveTimeout(60_000),
      message: `${label}: OpenPost must leave the code page after the exchange`,
    })
    .not.toContain("/accounts/mastodon/callback");
  await gotoOnion(page, `${env.appBaseUrl}/settings?tab=accounts`, { waitUntil: "domcontentloaded" });
  await expect(
    mastodonChannelActions(page, account),
    `${label}: ${account.handle} must be listed among the connected channels`,
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
  return account;
}

async function publishNow(page, account, text) {
  await page.getByRole("link", { name: /^new post$/i }).click();
  await page.getByRole("textbox", { name: /post text/i }).first().fill(text);
  await page.getByRole("main").getByRole("button", { name: /^more$/i }).click();
  await page.getByRole("menuitem", { name: /^publish now$/i }).click();
  const confirm = page.getByRole("alertdialog").or(page.getByRole("dialog"));
  if (await confirm.first().isVisible().catch(() => false)) {
    await confirm.first().getByRole("button", { name: /publish/i }).first().click();
  }
}

async function mastodonStatusExists(page, account, marker) {
  const handle = account.handle.replace(/^@/, "");
  const lookup = await page.request.get(`${env.mastodonBaseUrl}/api/v1/accounts/lookup?acct=${encodeURIComponent(handle)}`);
  if (!lookup.ok()) {
    return false;
  }
  const { id } = await lookup.json();
  const statuses = await page.request.get(`${env.mastodonBaseUrl}/api/v1/accounts/${id}/statuses?limit=20`);
  if (!statuses.ok()) {
    return false;
  }
  return (await statuses.json()).some((status) => String(status.content || "").includes(marker));
}

async function openPixelfedConnectDialog(page, label) {
  await gotoOnion(page, `${env.appBaseUrl}/settings?tab=accounts`, { waitUntil: "domcontentloaded" });
  const card = page.locator('[data-testid="provider-card-pixelfed"]');
  await expect(card, `${label}: the Pixelfed provider card must render`).toBeVisible({ timeout: resolveTimeout(60_000) });
  await card.getByRole("button", { name: /^connect$/i }).click();
  const dialog = page.getByRole("dialog", { name: /connect pixelfed/i });
  await dialog.getByRole("button", { name: /continue to pixelfed/i }).click();
  await dialog.getByRole("textbox", { name: /server address/i }).fill(env.pixelfedBaseUrl);
  return dialog;
}

function pixelfedChannelActions(page, account) {
  return page.getByRole("button", { name: new RegExp(`^actions for ${account.handle} · pixelfed$`, "i") });
}

const OOB_REDIRECT = "urn:ietf:wg:oauth:2.0:oob";

async function pixelfedAuthorizationCode(page, label, redirectedCode) {
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: `${label}: expected Pixelfed's sign-in or consent page` })
    .toContain(env.pixelfedBaseUrl);
  const password = page.locator('input[name="password"]');
  const authorize = page.getByRole("button", { name: /^authorize$/i });
  const codeShown = async () => (await page.locator("body").innerText()).includes('"code"');
  const consented = async () => Boolean(redirectedCode()) || (await codeShown()) || (await authorize.isVisible());
  await expect
    .poll(async () => (await consented()) || (await password.isVisible()), {
      timeout: resolveTimeout(60_000),
      message: `${label}: expected Pixelfed's sign-in form, consent screen or authorization code`,
    })
    .toBe(true);
  if (!(await consented()) && (await password.isVisible())) {
    await page.locator('input[name="email"]').fill(env.adminEmail);
    await password.fill(env.adminPassword);
    await page.locator("form").filter({ has: password }).locator('button[type="submit"]').click();
  }
  await expect
    .poll(consented, {
      timeout: resolveTimeout(60_000),
      message: `${label}: expected Pixelfed's consent screen or its authorization code`,
    })
    .toBe(true);
  if (redirectedCode()) {
    return redirectedCode();
  }
  if (await authorize.isVisible()) {
    await authorize.click();
  }
  await expect
    .poll(codeShown, {
      timeout: resolveTimeout(60_000),
      message: `${label}: Pixelfed must answer the out-of-band approval with the authorization code`,
    })
    .toBe(true);
  return JSON.parse(await page.locator("body").innerText()).code;
}

async function connectPixelfedAccount(page, label) {
  const account = { handle: `@${env.adminUsername}` };
  let redirected = "";
  const capture = (response) => {
    const location = response.headers().location || "";
    if (location.startsWith(OOB_REDIRECT)) {
      redirected = new URLSearchParams(location.split("?")[1] || "").get("code") || "";
    }
  };
  page.on("response", capture);
  const dialog = await openPixelfedConnectDialog(page, label);
  await dialog.getByRole("button", { name: /^connect$/i }).click();
  const code = await pixelfedAuthorizationCode(page, label, () => redirected);
  page.off("response", capture);
  expect(code, `${label}: Pixelfed must issue an authorization code`).toBeTruthy();
  const codeDialog = await openPixelfedConnectDialog(page, label);
  await codeDialog.getByRole("button", { name: /^code$/i }).click();
  await page.getByRole("textbox", { name: /authorization code/i }).fill(code);
  await page.getByRole("button", { name: /connect account/i }).click();
  await expect
    .poll(() => new URL(page.url()).pathname, {
      timeout: resolveTimeout(60_000),
      message: `${label}: OpenPost must leave the code page after the exchange`,
    })
    .not.toContain("/accounts/pixelfed/callback");
  await gotoOnion(page, `${env.appBaseUrl}/settings?tab=accounts`, { waitUntil: "domcontentloaded" });
  await expect(
    pixelfedChannelActions(page, account),
    `${label}: ${account.handle} must be listed among the connected Pixelfed channels`,
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
  return account;
}

async function apiRequest(page, headers, method, path, data) {
  const response = await page.request.fetch(`${env.appBaseUrl}/api/v1${path}`, { method, headers, data });
  expect(response.ok(), `${method} ${path} must succeed, got HTTP ${response.status()}`).toBeTruthy();
  return response.status() === 204 ? null : response.json();
}

function apiSession() {
  return { Origin: new URL(env.appBaseUrl).origin };
}

async function apiAccount(page, headers, platform) {
  for (const workspace of await apiRequest(page, headers, "GET", "/workspaces")) {
    const accounts = await apiRequest(page, headers, "GET", `/accounts?workspace_id=${workspace.id}`);
    const account = accounts.find((item) => item.platform === platform);
    if (account) {
      return { workspace: workspace.id, account: account.id };
    }
  }
  throw new Error(`no connected ${platform} account in any workspace`);
}

async function apiUploadImage(page, headers, workspace, fileName) {
  const buffer = uniquePng(fileName);
  const session = await apiRequest(page, headers, "POST", "/media/upload-session", {
    workspace_id: workspace,
    filename: fileName,
    mime_type: "image/png",
    size: buffer.length,
  });
  const target = new URL(session.upload.url, env.appBaseUrl);
  const uploadHeaders = { ...(session.upload.headers || {}) };
  if (target.origin === new URL(env.appBaseUrl).origin) {
    Object.assign(uploadHeaders, headers);
  }
  const upload = await page.request.fetch(target.toString(), { method: session.upload.method, headers: uploadHeaders, data: buffer });
  expect(upload.ok(), `the media upload must succeed, got HTTP ${upload.status()}`).toBeTruthy();
  const complete = new URL(session.complete_url, env.appBaseUrl).pathname.replace(/^\/api\/v1/, "");
  await apiRequest(page, headers, "POST", complete, { workspace_id: workspace });
  return session.media_id;
}

async function apiPublishImage(page, headers, target, text, label) {
  const media = await apiUploadImage(page, headers, target.workspace, `${label}-${Date.now()}.png`);
  const publication = await apiRequest(page, headers, "POST", "/publications", {
    workspace_id: target.workspace,
    title: text,
    content_profile: "image_post",
    source_text: text,
    social_account_ids: [target.account],
    renditions: [{ social_account_id: target.account, settings: {} }],
    media: [{ media_id: media }],
  });
  await apiRequest(page, headers, "POST", `/publications/${publication.id}/publish-now`, {
    expected_revision: publication.revision,
  });
  let rendition = {};
  await expect
    .poll(
      async () => {
        const current = await apiRequest(page, headers, "GET", `/publications/${publication.id}`);
        rendition = (current.renditions || [])[0] || {};
        return rendition.status;
      },
      { timeout: resolveTimeout(180_000), message: `${label}: the ${text} destination must end published` },
    )
    .toBe("published");
  return rendition;
}

async function beforeEach({ page }) {
  await page.setViewportSize({ width: 1440, height: 1100 });
  expect(env.appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(env.canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
}

module.exports = {
  env,
  LOGIN_PATH,
  gotoLogin,
  onLoginPage,
  assertAuthenticated,
  signInViaLocal,
  signInViaOidc,
  oidcProviderButton,
  openInstanceAdministration,
  assertInstanceAdministrationDenied,
  openComposer,
  assertWorkspaceHidden,
  uploadMedia,
  connectMastodonAccount,
  connectPixelfedAccount,
  apiSession,
  apiRequest,
  apiAccount,
  apiPublishImage,
  disconnectAccount,
  publishNow,
  mastodonStatusExists,
  logout,
  beforeEach,
  skipUnlessServiceEnabled,
  skipOnOnionSibling,
};
