const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceDisabled, skipUnlessServiceEnabled } = require("./service-gating");
const {
  decodeDotenvQuotedValue,
  gotoOnion,
  inAppLogout,
  installCspViolationObserver,
  keycloakAdminSetUserAttributes,
  normalizeBaseUrl,
} = require("./personas");

const keycloakBaseUrl = normalizeBaseUrl(process.env.KEYCLOAK_BASE_URL || "");
const realmName = decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME || "");
const superAdminUsername = decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME || "");
const superAdminPassword = decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD || "");
const lamBaseUrl = normalizeBaseUrl(process.env.LAM_BASE_URL || "");
const lamLoginPassword =
  decodeDotenvQuotedValue(process.env.LDAP_ADMIN_PASSWORD || "") || decodeDotenvQuotedValue(process.env.LAM_PASSWORD || "");

const KEYCLOAK_MIDDLE_NAME_ATTRIBUTE = "middleName";
const MIDDLE_NAME_FIELD = "input[name='middlename']";
const MOODLE_FIELD_BY_KEYCLOAK_ATTRIBUTE = {
  street: "address",
  locality: "city",
  country: "country",
};

async function expectMoodleMiddleName(shared, page, value, source) {
  await gotoOnion(page, `${shared.env.moodleBaseUrl}/user/edit.php`, { waitUntil: "domcontentloaded" });
  await expect(
    page.locator("#id_submitbutton"),
    "the profile-edit form must render before its middle name can be read",
  ).toBeVisible({ timeout: resolveTimeout(30_000) });
  await expect(
    page.locator(MIDDLE_NAME_FIELD).first(),
    `${source} must overwrite biber's Moodle middle name on this login`,
  ).toHaveValue(value, { timeout: resolveTimeout(30_000) });
  await gotoOnion(page, `${shared.env.moodleBaseUrl}/my/`, { waitUntil: "domcontentloaded" });
  await inAppLogout(page);
}

async function lamSignIn(page) {
  await gotoOnion(page, `${lamBaseUrl}/lam/templates/login.php`, { waitUntil: "load" });
  const passwordInput = page.locator("input[name='passwd'], input[name='password'], input#passwd").first();
  await expect(passwordInput, "the LAM native login form must render").toBeVisible({ timeout: resolveTimeout(30_000) });
  await passwordInput.fill(lamLoginPassword);
  await page.locator("button[type='submit'], input[type='submit']").first().click({ timeout: resolveTimeout(30_000) });
  await page.waitForLoadState("networkidle");
}

async function lamWriteBiberInitials(shared, page, value) {
  await gotoOnion(page, `${lamBaseUrl}/lam/templates/lists/list.php?type=user`, { waitUntil: "load" });
  const filter = page.locator("input[type='text'][name='filter_uid'], input[type='text'][name^='filter_']").first();
  if (await filter.isVisible().catch(() => false)) {
    await filter.fill(shared.env.biberUsername);
    await filter.press("Enter");
    await page.waitForLoadState("networkidle");
  }
  const biberRow = page.locator(`tr:has(td:text-is("${shared.env.biberUsername}"))`).first();
  await expect(biberRow, "biber must appear in the LAM user list").toBeVisible({ timeout: resolveTimeout(30_000) });
  await biberRow.locator(`a[href*="edit.php"][href*="${shared.env.biberUsername}"]`).first().click({ timeout: resolveTimeout(30_000) });
  await page.waitForLoadState("networkidle");

  const initials = page.locator("input[name='initials']").first();
  await expect(initials, "LAM must render biber's initials field").toBeVisible({ timeout: resolveTimeout(30_000) });
  const previous = await initials.inputValue();
  await initials.fill(value);
  await page.locator("[name='accountContainerSaveAccount']").first().click({ timeout: resolveTimeout(30_000) });
  await page.waitForLoadState("networkidle");
  await expect(
    page.locator("body"),
    "LAM must report the LDAP write of biber's initials as successful",
  ).toContainText(/successful|erfolgreich/i, { timeout: resolveTimeout(30_000) });
  return previous;
}

exports.register = function (shared) {
  test.describe("moodle profile sync", () => {
    test("biber: a middle name set in Keycloak reaches the Moodle profile on the next OIDC login", async ({ browser }) => {
      skipUnlessServiceEnabled("sso");
      test.setTimeout(resolveTimeout(240_000));
      expect(keycloakBaseUrl, "KEYCLOAK_BASE_URL must be set").toBeTruthy();
      expect(superAdminUsername, "SUPER_ADMIN_USERNAME must be set").toBeTruthy();
      expect(superAdminPassword, "SUPER_ADMIN_PASSWORD must be set").toBeTruthy();
      expect(realmName, "KEYCLOAK_REALM_NAME must be set").toBeTruthy();

      const probe = `OIDC-${Date.now()}`;
      const context = await browser.newContext({ ignoreHTTPSErrors: true });
      let previous = null;
      try {
        previous = await keycloakAdminSetUserAttributes(
          context.request,
          keycloakBaseUrl,
          realmName,
          shared.env.biberUsername,
          { [KEYCLOAK_MIDDLE_NAME_ATTRIBUTE]: probe },
          superAdminUsername,
          superAdminPassword,
        );

        const page = await context.newPage();
        await installCspViolationObserver(page);
        await shared.loginAsDirectoryUser(page, shared.env.biberUsername, shared.env.biberPassword);
        await expectMoodleMiddleName(shared, page, probe, "the middle_name claim of the OIDC login");
      } finally {
        if (previous) {
          await keycloakAdminSetUserAttributes(
            context.request,
            keycloakBaseUrl,
            realmName,
            shared.env.biberUsername,
            previous,
            superAdminUsername,
            superAdminPassword,
          ).catch((error) => console.warn(`Restoring the middle name of ${shared.env.biberUsername} failed: ${error}`));
        }
        await context.close().catch(() => {});
      }
    });

    test("biber: street, locality and country set in Keycloak fill the Moodle address, city and country on the next OIDC login", async ({ browser }) => {
      skipUnlessServiceEnabled("sso");
      test.setTimeout(resolveTimeout(240_000)); // one Keycloak attribute write and restore around one OIDC round-trip
      expect(keycloakBaseUrl, "KEYCLOAK_BASE_URL must be set").toBeTruthy();
      expect(superAdminUsername, "SUPER_ADMIN_USERNAME must be set").toBeTruthy();
      expect(superAdminPassword, "SUPER_ADMIN_PASSWORD must be set").toBeTruthy();
      expect(realmName, "KEYCLOAK_REALM_NAME must be set").toBeTruthy();

      const suffix = String(Date.now()).slice(-6);
      const attributes = { street: `Claimstrasse ${suffix}`, locality: `Hamburg ${suffix}`, country: "DE" };
      const context = await browser.newContext({ ignoreHTTPSErrors: true });
      let previous = null;
      try {
        previous = await keycloakAdminSetUserAttributes(
          context.request,
          keycloakBaseUrl,
          realmName,
          shared.env.biberUsername,
          attributes,
          superAdminUsername,
          superAdminPassword,
        );

        const page = await context.newPage();
        await installCspViolationObserver(page);
        await shared.loginAsDirectoryUser(page, shared.env.biberUsername, shared.env.biberPassword);
        await gotoOnion(page, `${shared.env.moodleBaseUrl}/user/edit.php`, { waitUntil: "domcontentloaded" });
        await expect(
          page.locator("#id_submitbutton"),
          "the profile-edit form must render before its address can be read",
        ).toBeVisible({ timeout: resolveTimeout(30_000) });
        for (const [attribute, field] of Object.entries(MOODLE_FIELD_BY_KEYCLOAK_ATTRIBUTE)) {
          await expect(
            page.locator(`[name='${field}']`).first(),
            `the flat ${attribute} claim of the moodle scope must fill biber's Moodle ${field}`,
          ).toHaveValue(attributes[attribute], { timeout: resolveTimeout(30_000) });
        }
        await gotoOnion(page, `${shared.env.moodleBaseUrl}/my/`, { waitUntil: "domcontentloaded" });
        await inAppLogout(page);
      } finally {
        if (previous) {
          await keycloakAdminSetUserAttributes(
            context.request,
            keycloakBaseUrl,
            realmName,
            shared.env.biberUsername,
            previous,
            superAdminUsername,
            superAdminPassword,
          ).catch((error) => console.warn(`Restoring the address of ${shared.env.biberUsername} failed: ${error}`));
        }
        await context.close().catch(() => {});
      }
    });

    test("biber: an initials change written to LDAP reaches the Moodle profile on the next LDAP login", async ({ browser }) => {
      skipUnlessServiceEnabled("ldap");
      skipUnlessServiceEnabled("lam");
      skipUnlessServiceDisabled("sso");
      test.setTimeout(resolveTimeout(300_000));
      expect(lamBaseUrl, "LAM_BASE_URL must be set").toBeTruthy();
      expect(lamLoginPassword, "LDAP_ADMIN_PASSWORD or LAM_PASSWORD must be set").toBeTruthy();

      const probe = `LDAP-${Date.now()}`;
      const lamContext = await browser.newContext({ ignoreHTTPSErrors: true });
      const moodleContext = await browser.newContext({ ignoreHTTPSErrors: true });
      let previous = null;
      try {
        const lamPage = await lamContext.newPage();
        await lamSignIn(lamPage);
        previous = await lamWriteBiberInitials(shared, lamPage, probe);

        const page = await moodleContext.newPage();
        await installCspViolationObserver(page);
        await shared.loginAsDirectoryUser(page, shared.env.biberUsername, shared.env.biberPassword);
        await expectMoodleMiddleName(shared, page, probe, "the LDAP initials attribute of the auth_ldap login");
      } finally {
        if (previous !== null) {
          try {
            const restorePage = await lamContext.newPage();
            await lamWriteBiberInitials(shared, restorePage, previous);
          } catch (error) {
            console.warn(`Restoring the initials of ${shared.env.biberUsername} failed: ${error}`);
          }
        }
        await lamContext.close().catch(() => {});
        await moodleContext.close().catch(() => {});
      }
    });
  });
};
