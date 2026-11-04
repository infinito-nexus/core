const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const {
  decodeDotenvQuotedValue,
  gotoOnion,
  installCspViolationObserver,
  keycloakAdminSetUserAttributes,
  normalizeBaseUrl,
  requireDotenvValue,
} = require("./personas");
const { signInViaKeycloak } = require("./joomla-session");

const base = normalizeBaseUrl(process.env.JOOMLA_BASE_URL);
const keycloakBaseUrl = normalizeBaseUrl(process.env.KEYCLOAK_BASE_URL);
const realmName = decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME);
const superAdminUsername = decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME);
const superAdminPassword = decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD);
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const localeAttribute = requireDotenvValue(process.env.PROFILE_ATTRIBUTE_LOCALE, "PROFILE_ATTRIBUTE_LOCALE");
const zoneinfoAttribute = requireDotenvValue(process.env.PROFILE_ATTRIBUTE_ZONEINFO, "PROFILE_ATTRIBUTE_ZONEINFO");

const LOCALE = "en";
const LANGUAGE_TAG = "en-GB";
const ZONEINFO = "Europe/Berlin";
const PROFILE_FIELD_BY_ATTRIBUTE = {
  phoneNumber: "#jform_profile_phone",
  street: "#jform_profile_address1",
  locality: "#jform_profile_city",
  region: "#jform_profile_region",
  postal_code: "#jform_profile_postal_code",
  country: "#jform_profile_country",
  website: "#jform_profile_website",
};
const READ_ONLY_FIELDS = ["#jform_name", "#jform_email1", ...Object.values(PROFILE_FIELD_BY_ATTRIBUTE)];
const LOCKED_SELECTS = ["#jform_params_language", "#jform_params_timezone"];

test.use({ ignoreHTTPSErrors: true });

test("profile: Keycloak locale, zoneinfo, phone, address and website reach biber's Joomla profile on login and stay read-only", async ({
  browser,
}) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(240_000)); // one Keycloak attribute write and restore around one OIDC round-trip and one profile save
  expect(base, "JOOMLA_BASE_URL must be set").toBeTruthy();

  const suffix = String(Date.now()).slice(-6);
  const contact = {
    phoneNumber: `+4940${suffix}`,
    street: `Claimstrasse ${suffix}`,
    locality: `Hamburg ${suffix}`,
    region: "Hamburg",
    postal_code: suffix.slice(0, 5),
    country: "DE",
    website: `${base}/biber-${suffix}`,
  };

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  let previous = null;
  try {
    previous = await keycloakAdminSetUserAttributes(
      context.request,
      keycloakBaseUrl,
      realmName,
      biberUsername,
      { [localeAttribute]: LOCALE, [zoneinfoAttribute]: ZONEINFO, ...contact },
      superAdminUsername,
      superAdminPassword,
    );

    const page = await context.newPage();
    await installCspViolationObserver(page);
    await signInViaKeycloak(page, base, biberUsername, biberPassword);

    await gotoOnion(page, `${base}/index.php?option=com_users&view=profile&layout=edit`);
    await expect(
      page.locator("#jform_params_timezone"),
      `the ${zoneinfoAttribute} claim must set biber's Joomla time zone`,
    ).toHaveValue(ZONEINFO, { timeout: resolveTimeout(30_000) });
    await expect(
      page.locator("#jform_params_language"),
      `the ${localeAttribute} claim "${LOCALE}" must resolve to the installed site language ${LANGUAGE_TAG}`,
    ).toHaveValue(LANGUAGE_TAG, { timeout: resolveTimeout(30_000) });
    for (const [attribute, field] of Object.entries(PROFILE_FIELD_BY_ATTRIBUTE)) {
      await expect(
        page.locator(field),
        `the Keycloak ${attribute} attribute must reach plg_user_profile's ${field} through the phone, address or profile scope`,
      ).toHaveValue(contact[attribute], { timeout: resolveTimeout(30_000) });
    }

    for (const field of READ_ONLY_FIELDS) {
      await expect(page.locator(field), `${field} must be read-only because every login overwrites it from Keycloak`).not.toBeEditable();
    }
    for (const field of LOCKED_SELECTS) {
      await expect(page.locator(field), `${field} must be locked because every login overwrites it from Keycloak`).toBeDisabled();
    }

    const storedName = await page.locator("#jform_name").inputValue();
    await page.locator("#jform_name").evaluate((field) => {
      field.readOnly = false;
    });
    await page.locator("#jform_name").fill(`${storedName} tampered`);
    await page.locator("#member-profile button[name='task'][value='profile.save']").click({ timeout: resolveTimeout(30_000) });
    await expect(
      page.locator("main .com-users-profile").first(),
      "saving the profile must succeed while the Keycloak-managed fields are locked",
    ).toBeVisible({ timeout: resolveTimeout(30_000) });

    await gotoOnion(page, `${base}/index.php?option=com_users&view=profile&layout=edit`);
    await expect(
      page.locator("#jform_name"),
      "a saved profile must keep the Keycloak name even when the read-only lock is bypassed",
    ).toHaveValue(storedName, { timeout: resolveTimeout(30_000) });
  } finally {
    if (previous) {
      await keycloakAdminSetUserAttributes(
        context.request,
        keycloakBaseUrl,
        realmName,
        biberUsername,
        previous,
        superAdminUsername,
        superAdminPassword,
      ).catch((error) => console.warn(`Restoring the profile attributes of ${biberUsername} failed: ${error}`));
    }
    await context.clearCookies().catch(() => {});
    await context.close().catch(() => {});
  }
});
