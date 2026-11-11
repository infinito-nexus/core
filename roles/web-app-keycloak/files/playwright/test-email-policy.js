const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { gotoOnion, normalizeBaseUrl, performKeycloakLoginForm, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

const appBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const realmName = requireDotenvValue(process.env.KEYCLOAK_REALM_NAME, "KEYCLOAK_REALM_NAME");
const biberUsername = requireDotenvValue(process.env.BIBER_USERNAME, "BIBER_USERNAME");
const biberPassword = requireDotenvValue(process.env.BIBER_PASSWORD, "BIBER_PASSWORD");
const emailMailbox = requireDotenvValue(process.env.KEYCLOAK_EMAIL_POLICY, "KEYCLOAK_EMAIL_POLICY") === "mailbox";
const mailboxAttribute = requireDotenvValue(
  process.env.KEYCLOAK_EMAIL_MAILBOX_ATTRIBUTE,
  "KEYCLOAK_EMAIL_MAILBOX_ATTRIBUTE",
);

function isProfileRead(response) {
  const url = new URL(response.url());
  return (
    response.request().method() === "GET" &&
    response.ok() &&
    url.pathname.replace(/\/$/, "") === `/realms/${realmName}/account` &&
    url.searchParams.get("userProfileMetadata") === "true"
  );
}

exports.register = function () {
  test("biber: email policy: biber cannot change the primary address directly", async ({ page }) => {
    skipUnlessServiceEnabled("ldap");
    test.setTimeout(resolveTimeout(180_000));
    const primary = emailMailbox ? mailboxAttribute : "email";
    const profileRead = page.waitForResponse(isProfileRead, { timeout: resolveTimeout(120_000) });

    await gotoOnion(page, `${appBaseUrl}/realms/${realmName}/account/`);
    const signInButton = page.locator("a, button").filter({ hasText: /sign\s*in|log\s*in|anmelden/i }).first();
    if ((await signInButton.count().catch(() => 0)) > 0) {
      await signInButton.click({ timeout: resolveTimeout(30_000) });
    }
    await performKeycloakLoginForm(page, biberUsername, biberPassword);

    const profile = await (await profileRead).json();
    const attribute = ((profile.userProfileMetadata || {}).attributes || []).find(
      (candidate) => candidate.name === primary,
    );
    expect(attribute, `the account console MUST show biber the primary address attribute ${primary}`).toBeTruthy();
    expect(
      attribute.readOnly,
      `the account console MUST offer biber no direct edit of the primary address attribute ${primary}`,
    ).toBe(true);
  });
};
