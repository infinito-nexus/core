const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const {
  decodeDotenvQuotedValue,
  gotoOnion,
  keycloakAdminAddUserToGroup,
  keycloakRemoveUserFromGroupViaRest,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  requireDotenvValue,
} = require("./personas");

test.use({ ignoreHTTPSErrors: true });

const baseUrl = normalizeBaseUrl(requireDotenvValue(process.env.BOOKWYRM_BASE_URL, "BOOKWYRM_BASE_URL"));
const biberUsername = requireDotenvValue(process.env.BIBER_USERNAME, "BIBER_USERNAME");
const biberPassword = requireDotenvValue(process.env.BIBER_PASSWORD, "BIBER_PASSWORD");
const keycloakBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.KEYCLOAK_BASE_URL, "KEYCLOAK_BASE_URL"));
const realmName = requireDotenvValue(process.env.KEYCLOAK_REALM_NAME, "KEYCLOAK_REALM_NAME");
const superAdminUsername = decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME || "");
const superAdminPassword = decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD || "");
const moderatorGroupPath = decodeDotenvQuotedValue(process.env.RBAC_MODERATOR_GROUP_PATH || "");
const administratorGroupPath = decodeDotenvQuotedValue(process.env.RBAC_ADMINISTRATOR_GROUP_PATH || "");

const CLEANUP_TIMEOUT_MS = 30_000;

function withDeadline(promise, label) {
  return Promise.race([
    promise,
    new Promise((_, reject) => setTimeout(() => reject(new Error(`${label} timed out`)), CLEANUP_TIMEOUT_MS)),
  ]);
}

async function signInAsBiber(browser) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  await gotoOnion(page, `${baseUrl}/`);
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "the oauth2 proxy must hand biber to Keycloak" })
    .toContain("openid-connect/auth");
  await performKeycloakLoginForm(page, biberUsername, biberPassword);
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(90_000), message: `expected redirect back to ${baseUrl}` })
    .toContain(baseUrl.replace(/^https?:\/\//, ""));
  await gotoOnion(page, `${baseUrl}/preferences/profile`, { waitUntil: "domcontentloaded" });
  await expect(
    page.locator('form[name="edit-profile"]'),
    "the open gate MUST admit biber into a real BookWyrm session",
  ).toBeVisible({ timeout: resolveTimeout(30_000) });
  return { context, page };
}

async function moderationStatus(page) {
  const response = await gotoOnion(page, `${baseUrl}/settings/users`, { waitUntil: "domcontentloaded" });
  return response ? response.status() : 0;
}

async function removeBiberFromGroup(browser, groupPath) {
  const cleanup = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    await withDeadline(
      keycloakRemoveUserFromGroupViaRest(
        cleanup.request,
        keycloakBaseUrl,
        realmName,
        superAdminUsername,
        superAdminPassword,
        groupPath,
        biberUsername,
      ),
      `removing biber from ${groupPath}`,
    );
  } catch (err) {
    console.warn(`Cleanup removal of biber from ${groupPath} failed: ${err}`);
  } finally {
    await cleanup.close().catch(() => {});
  }
}

test("biber: the open gate admits a realm user without a role group and grants no moderation", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(120_000)); // Keycloak round trip through the oauth2 proxy
  const { context, page } = await signInAsBiber(browser);
  try {
    expect(await moderationStatus(page), "biber without a role group MUST NOT reach /settings/users").toBe(403);
  } finally {
    await context.close().catch(() => {});
  }
});

test("biber: the moderator role group grants BookWyrm moderation and leaving it revokes it", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(300_000)); // two Keycloak round trips around a group change
  expect(moderatorGroupPath, "RBAC_MODERATOR_GROUP_PATH must be set").toBeTruthy();
  expect(superAdminUsername, "SUPER_ADMIN_USERNAME must be set").toBeTruthy();
  expect(superAdminPassword, "SUPER_ADMIN_PASSWORD must be set").toBeTruthy();

  const admin = await browser.newContext({ ignoreHTTPSErrors: true });
  let joined = false;
  try {
    joined = await keycloakAdminAddUserToGroup(
      admin.request,
      keycloakBaseUrl,
      realmName,
      moderatorGroupPath,
      biberUsername,
      superAdminUsername,
      superAdminPassword,
    );
    const promoted = await signInAsBiber(browser);
    try {
      expect(await moderationStatus(promoted.page), "the moderator group MUST open /settings/users").toBeLessThan(400);
    } finally {
      await promoted.context.close().catch(() => {});
    }
  } finally {
    await admin.close().catch(() => {});
    if (joined) {
      await removeBiberFromGroup(browser, moderatorGroupPath);
    }
  }

  const demoted = await signInAsBiber(browser);
  try {
    expect(await moderationStatus(demoted.page), "leaving the moderator group MUST revoke /settings/users").toBe(403);
  } finally {
    await demoted.context.close().catch(() => {});
  }
});

test("biber: a forged groups header cannot grant a BookWyrm role", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(120_000)); // Keycloak round trip through the oauth2 proxy
  expect(administratorGroupPath, "RBAC_ADMINISTRATOR_GROUP_PATH must be set").toBeTruthy();
  const { context, page } = await signInAsBiber(browser);
  try {
    await page.setExtraHTTPHeaders({
      "X-Forwarded-Groups": administratorGroupPath,
    });
    expect(
      await moderationStatus(page),
      "nginx MUST overwrite X-Forwarded-Groups, so an injected administrator path grants nothing",
    ).toBe(403);
  } finally {
    await context.close().catch(() => {});
  }
});
