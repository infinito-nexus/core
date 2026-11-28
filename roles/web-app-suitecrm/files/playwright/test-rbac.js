const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { decodeDotenvQuoted, keycloakAdminSetUserAttributes, normalizeBaseUrl } = require("./personas");
const {
  holdsAdministration,
  keycloak,
  postAssertion,
  rbacGroups,
  samlLogin,
  sessionStatus,
  withUserInGroups,
} = require("./saml-login");

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL);
const biber = {
  username: decodeDotenvQuoted(process.env.BIBER_USERNAME),
  password: decodeDotenvQuoted(process.env.BIBER_PASSWORD),
};
const PROFILE = {
  phoneNumber: "+49 30 7654321",
  title: "Account Manager",
  department: "Customer Success",
};

async function signInAsBiber(browser) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  const status = await samlLogin(page, appBaseUrl, biber.username, biber.password);
  return { context, page, status };
}

async function ownDetailView(page, userId) {
  expect(userId, "session-status must name the signed-in user's id").toBeTruthy();
  const response = await page.request.get(
    `${appBaseUrl}/legacy/index.php?module=Users&action=DetailView&record=${encodeURIComponent(userId)}`,
    { timeout: resolveTimeout(60_000) },
  );
  expect(response.status(), "the own user record must answer").toBeLessThan(400);
  return response.text();
}

exports.register = function () {
  test.describe.serial("rbac: SAML role groups and directory profile", () => {
    test("rbac: biber without a SuiteCRM role group is refused at the SAML sign-in", async ({ page }) => {
      skipUnlessServiceEnabled("sso");
      test.setTimeout(resolveTimeout(180_000)); // SAML round trip that ends in the refusal

      await postAssertion(page, appBaseUrl, biber.username, biber.password);
      const status = await sessionStatus(page, appBaseUrl);
      expect(
        status.active,
        "files/php/iam/saml_directory_sync.php must refuse an assertion that names no role group of SuiteCRM",
      ).toBe(false);
      await page.context().clearCookies();
    });

    test("rbac: the administrator group grants the admin flag at sign-in and leaving it withdraws the flag", async ({ browser }) => {
      skipUnlessServiceEnabled("sso");
      test.setTimeout(resolveTimeout(420_000)); // two group changes and two SAML round trips

      await withUserInGroups(browser, biber.username, [rbacGroups.user, rbacGroups.administrator], async (leave) => {
        const promoted = await signInAsBiber(browser);
        try {
          expect(promoted.status.active, "an administrator group member must get a session").toBe(true);
          expect(
            await holdsAdministration(promoted.page, appBaseUrl),
            "the administrator group in the assertion must grant the SuiteCRM admin flag at this sign-in",
          ).toBe(true);
        } finally {
          await promoted.context.close().catch(() => {});
        }

        await leave(rbacGroups.administrator);

        const demoted = await signInAsBiber(browser);
        try {
          expect(demoted.status.active, "a user group member must still get a session").toBe(true);
          expect(
            await holdsAdministration(demoted.page, appBaseUrl),
            "leaving the administrator group must withdraw the admin flag at the next sign-in",
          ).toBe(false);
        } finally {
          await demoted.context.close().catch(() => {});
        }
      });
    });

    test("rbac: the directory profile reaches the SuiteCRM user record at every SAML sign-in", async ({ browser }) => {
      skipUnlessServiceEnabled("sso");
      test.setTimeout(resolveTimeout(300_000)); // attribute update, group join, SAML round trip and restore

      await withUserInGroups(browser, biber.username, [rbacGroups.user], async (_leave, request) => {
        let previous = null;
        try {
          previous = await keycloakAdminSetUserAttributes(
            request,
            keycloak.baseUrl,
            keycloak.realm,
            biber.username,
            PROFILE,
            keycloak.username,
            keycloak.password,
          );
          const session = await signInAsBiber(browser);
          try {
            expect(session.status.active, "a user group member must get a session").toBe(true);
            const record = await ownDetailView(session.page, session.status.id);
            for (const [attribute, value] of Object.entries(PROFILE)) {
              expect(record, `the Keycloak attribute ${attribute} must reach the SuiteCRM user record`).toContain(value);
            }
          } finally {
            await session.context.close().catch(() => {});
          }
        } finally {
          if (previous) {
            await keycloakAdminSetUserAttributes(
              request,
              keycloak.baseUrl,
              keycloak.realm,
              biber.username,
              previous,
              keycloak.username,
              keycloak.password,
            ).catch((err) => console.warn(`Restoring biber's Keycloak attributes failed: ${err}`));
          }
        }
      });
    });
  });
};
