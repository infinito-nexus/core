const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const {
  gotoOnion,
  installCspViolationObserver,
  keycloakAdminSetUserAttributes,
  keycloakAdminToken,
  requireDotenvValue,
} = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

async function readKeycloakUser(request, env) {
  const token = await keycloakAdminToken(
    request,
    env.keycloakBaseUrl,
    env.superAdminUsername,
    env.superAdminPassword
  );
  const response = await request.get(
    `${env.keycloakBaseUrl}/admin/realms/${encodeURIComponent(env.realmName)}/users?username=${encodeURIComponent(env.biberUsername)}&exact=true`,
    { headers: { Authorization: `Bearer ${token}` }, timeout: resolveTimeout(30_000) }
  );
  expect(response.ok(), `Keycloak user lookup for ${env.biberUsername} failed: ${response.status()}`).toBe(true);
  const user = (await response.json()).find((candidate) => candidate.username === env.biberUsername);
  expect(user, `Keycloak user ${env.biberUsername} must exist`).toBeTruthy();
  return user;
}

exports.register = function (shared) {
  test("biber: Keycloak name, email, website and locale sync into the WordPress profile on OIDC login and stay read-only", async ({
    browser,
  }) => {
    skipUnlessServiceEnabled("sso");
    skipUnlessServiceEnabled("javascript");
    test.setTimeout(resolveTimeout(180_000));
    const { env } = shared;
    const website = `${env.wpBaseUrl}/biber-${Date.now().toString(36)}`;
    expect(
      website.length,
      "WordPress rejects the whole profile update of a user_url over 100 characters"
    ).toBeLessThanOrEqual(100);
    const mailbox = requireDotenvValue(process.env.KEYCLOAK_EMAIL_POLICY, "KEYCLOAK_EMAIL_POLICY") === "mailbox";
    const adminCtx = await browser.newContext({ ignoreHTTPSErrors: true });
    let previous = null;

    try {
      const keycloakUser = await readKeycloakUser(adminCtx.request, env);
      const claimedEmail = mailbox ? requireDotenvValue(process.env.BIBER_EMAIL, "BIBER_EMAIL") : keycloakUser.email;
      previous = await keycloakAdminSetUserAttributes(
        adminCtx.request,
        env.keycloakBaseUrl,
        env.realmName,
        env.biberUsername,
        { [env.profileAttributeWebsite]: website, [env.profileAttributeLocale]: "de" },
        env.superAdminUsername,
        env.superAdminPassword
      );

      const biberCtx = await browser.newContext({
        ignoreHTTPSErrors: true,
        viewport: { width: 1440, height: 1100 },
      });
      try {
        const page = await biberCtx.newPage();
        await installCspViolationObserver(page);
        await shared.wpAdminLoginViaOidc(page, env.wpBaseUrl, env.biberUsername, env.biberPassword);
        await gotoOnion(page, `${env.wpBaseUrl}/wp-admin/profile.php`, { waitUntil: "domcontentloaded" });

        await expect(
          page.locator("input#url"),
          "the Keycloak website attribute MUST reach the WordPress profile on login"
        ).toHaveValue(website, { timeout: resolveTimeout(30_000) });
        await expect(
          page.locator("input#email"),
          mailbox
            ? "under the mailbox policy the WordPress email MUST be the mailbox, not Keycloak's secondary address"
            : "the WordPress email MUST be the Keycloak email"
        ).toHaveValue(claimedEmail);
        await expect(page.locator("input#first_name")).toHaveValue(keycloakUser.firstName);
        await expect(page.locator("input#last_name")).toHaveValue(keycloakUser.lastName);
        await expect(
          page.locator("#wp-admin-bar-my-account .display-name").first(),
          "the WordPress display name MUST be the Keycloak full name"
        ).toHaveText(`${keycloakUser.firstName} ${keycloakUser.lastName}`);
        await expect(
          page.locator("html"),
          "the Keycloak locale MUST become the WordPress user locale"
        ).toHaveAttribute("lang", /^de(-|$)/);

        for (const field of ["input#first_name", "input#last_name", "input#email", "input#url"]) {
          await expect(
            page.locator(field),
            `${field} MUST be read-only on profile.php because the OIDC login overwrites it`
          ).not.toBeEditable();
        }
        await expect(
          page.locator("select#display_name"),
          "the display name MUST be locked on profile.php because the OIDC login overwrites it"
        ).toBeDisabled();

        const firstName = page.locator("input#first_name");
        await firstName.evaluate((field) => {
          field.readOnly = false;
        });
        await firstName.fill(`${keycloakUser.firstName}-tampered`);
        await page.locator("input#submit").click();
        await expect
          .poll(() => page.url(), {
            timeout: resolveTimeout(30_000),
            message: "saving profile.php MUST succeed while the IdP-managed fields are locked",
          })
          .toContain("updated=");
        await expect(
          page.locator("input#first_name"),
          "a saved profile MUST keep the Keycloak first name even when the read-only lock is bypassed"
        ).toHaveValue(keycloakUser.firstName);

        await shared.wpSignOut(page, env.wpBaseUrl);
      } finally {
        await biberCtx.close().catch(() => {});
      }
    } finally {
      if (previous) {
        await keycloakAdminSetUserAttributes(
          adminCtx.request,
          env.keycloakBaseUrl,
          env.realmName,
          env.biberUsername,
          previous,
          env.superAdminUsername,
          env.superAdminPassword
        ).catch((err) => console.warn(`Restoring biber's Keycloak profile attributes failed: ${err}`));
      }
      await adminCtx.close().catch(() => {});
    }
  });
};
