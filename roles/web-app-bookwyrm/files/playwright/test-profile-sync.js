const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const {
  decodeDotenvQuotedValue,
  gotoOnion,
  keycloakAdminSetUserAttributes,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  requireDotenvValue,
} = require("./personas");

test.use({ ignoreHTTPSErrors: true });

const baseUrl = normalizeBaseUrl(requireDotenvValue(process.env.BOOKWYRM_BASE_URL, "BOOKWYRM_BASE_URL"));
const biberUsername = requireDotenvValue(process.env.BIBER_USERNAME, "BIBER_USERNAME");
const biberPassword = requireDotenvValue(process.env.BIBER_PASSWORD, "BIBER_PASSWORD");
const biberFullName = requireDotenvValue(process.env.BIBER_FULL_NAME, "BIBER_FULL_NAME");
const keycloakBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.KEYCLOAK_BASE_URL, "KEYCLOAK_BASE_URL"));
const realmName = requireDotenvValue(process.env.KEYCLOAK_REALM_NAME, "KEYCLOAK_REALM_NAME");
const superAdminUsername = decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME || "");
const superAdminPassword = decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD || "");

const PROFILE = { locale: "de", zoneinfo: "Europe/Berlin" };
const BOOKWYRM_LANGUAGE = "de-de";
const LANGUAGE_FIELD = '[name="preferred_language"]';
const TIMEZONE_FIELD = '[name="preferred_timezone"]';

async function openProfileForm(context) {
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
  const form = page.locator('form[name="edit-profile"]');
  await expect(form, "biber must reach the BookWyrm profile form").toBeVisible({ timeout: resolveTimeout(30_000) });
  return form;
}

test("biber: name, language and time zone follow Keycloak, and a forged name header is overwritten", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(360_000)); // two gate round trips, a Keycloak attribute write and the profile form save
  expect(superAdminUsername, "SUPER_ADMIN_USERNAME must be set").toBeTruthy();
  expect(superAdminPassword, "SUPER_ADMIN_PASSWORD must be set").toBeTruthy();

  const before = await browser.newContext({ ignoreHTTPSErrors: true });
  let stored;
  try {
    const form = await openProfileForm(before);
    stored = {
      language: await form.locator(LANGUAGE_FIELD).inputValue(),
      timezone: await form.locator(TIMEZONE_FIELD).inputValue(),
    };
  } finally {
    await before.close().catch(() => {});
  }

  const admin = await browser.newContext({ ignoreHTTPSErrors: true });
  let previous = null;
  let context = null;
  try {
    previous = await keycloakAdminSetUserAttributes(
      admin.request,
      keycloakBaseUrl,
      realmName,
      biberUsername,
      PROFILE,
      superAdminUsername,
      superAdminPassword,
    );
    context = await browser.newContext({
      ignoreHTTPSErrors: true,
      extraHTTPHeaders: { "X-Forwarded-Name": "Forged Name", "X-Forwarded-Locale": "fr" },
    });
    const form = await openProfileForm(context);
    await expect(
      form.locator('[name="name"]'),
      "the display name must be the Keycloak name claim, not the header the browser sent",
    ).toHaveValue(biberFullName);
    await expect(form.locator(LANGUAGE_FIELD), "the language must follow the Keycloak locale attribute").toHaveValue(
      BOOKWYRM_LANGUAGE,
    );
    await expect(form.locator(TIMEZONE_FIELD), "the time zone must follow the Keycloak zoneinfo attribute").toHaveValue(
      PROFILE.zoneinfo,
    );

    await form.locator(LANGUAGE_FIELD).selectOption(stored.language);
    await form.locator(TIMEZONE_FIELD).selectOption(stored.timezone);
    await Promise.all([
      form.page().waitForLoadState("domcontentloaded", { timeout: resolveTimeout(60_000) }),
      form.locator('button[type="submit"]').first().click({ timeout: resolveTimeout(30_000) }),
    ]);
  } finally {
    if (previous) {
      await keycloakAdminSetUserAttributes(
        admin.request,
        keycloakBaseUrl,
        realmName,
        biberUsername,
        previous,
        superAdminUsername,
        superAdminPassword,
      ).catch((err) => console.warn(`Restoring biber's Keycloak locale and zoneinfo failed: ${err}`));
    }
    if (context) await context.close().catch(() => {});
    await admin.close().catch(() => {});
  }
});
