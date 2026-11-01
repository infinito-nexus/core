const { test, expect, request } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { keycloakAdminToken, requireDotenvValue } = require("./personas");

const RESTORE_DEADLINE_MS = 120_000;

/**
 * Args:
 *   username: Keycloak username whose profile is read and written.
 *   mutate: function that receives the current user representation and returns the one to store.
 * Returns: the user representation as it was before the write.
 */
async function rewriteKeycloakUser(username, mutate) {
  const kcBaseUrl = requireDotenvValue(process.env.KEYCLOAK_BASE_URL, "KEYCLOAK_BASE_URL").replace(/\/$/, "");
  const kcRealm = requireDotenvValue(process.env.KEYCLOAK_REALM, "KEYCLOAK_REALM");
  const api = await request.newContext({ ignoreHTTPSErrors: true });
  try {
    const token = await keycloakAdminToken(
      api,
      kcBaseUrl,
      requireDotenvValue(process.env.KEYCLOAK_ADMIN_USERNAME, "KEYCLOAK_ADMIN_USERNAME"),
      requireDotenvValue(process.env.KEYCLOAK_ADMIN_PASSWORD, "KEYCLOAK_ADMIN_PASSWORD"),
    );
    const headers = { Authorization: `Bearer ${token}` };
    const users = await (
      await api.get(`${kcBaseUrl}/admin/realms/${kcRealm}/users?username=${encodeURIComponent(username)}&exact=true`, { headers })
    ).json();
    expect(users, `Keycloak user ${username} must exist`).toHaveLength(1);
    const userUrl = `${kcBaseUrl}/admin/realms/${kcRealm}/users/${users[0].id}`;
    const before = await (await api.get(userUrl, { headers })).json();
    const resp = await api.put(userUrl, {
      headers: { ...headers, "Content-Type": "application/json" },
      data: mutate(before),
    });
    expect(resp.ok(), `Keycloak profile update of ${username} (HTTP ${resp.status()}: ${await resp.text()})`).toBeTruthy();
    return before;
  } finally {
    await api.dispose();
  }
}

async function sessionUser(page, openwebuiBaseUrl) {
  const token = await page.evaluate(() => localStorage.getItem("token"));
  expect(token, "Open WebUI must store a session token after the OIDC login").toBeTruthy();
  const resp = await page.request.get(`${openwebuiBaseUrl}/api/v1/auths/`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(resp.ok(), `Open WebUI session user (HTTP ${resp.status()})`).toBeTruthy();
  return resp.json();
}

exports.register = function (shared) {
  test("biber: a name and e-mail changed in Keycloak replace the Open WebUI profile on the next OIDC login", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(300_000));

    const { biberUsername, biberPassword, openwebuiBaseUrl, canonicalDomain } = shared.env;
    const stamp = Date.now().toString(36);
    const probeFirstName = `Probe${stamp}`;
    const probeEmail = `${biberUsername}+${stamp}@${canonicalDomain}`;
    const mailbox = requireDotenvValue(process.env.KEYCLOAK_EMAIL_POLICY, "KEYCLOAK_EMAIL_POLICY") === "mailbox";
    const claimedEmail = mailbox ? requireDotenvValue(process.env.BIBER_EMAIL, "BIBER_EMAIL") : probeEmail;

    await shared.signInViaDashboardOidc(page, biberUsername, biberPassword, "biber");
    await shared.expectSignInRequiredAfterLogout(page);

    let original = null;
    try {
      original = await rewriteKeycloakUser(biberUsername, (user) => ({
        ...user,
        firstName: probeFirstName,
        email: probeEmail,
        emailVerified: true,
      }));

      await shared.signInViaDashboardOidc(page, biberUsername, biberPassword, "biber");
      const user = await sessionUser(page, openwebuiBaseUrl);
      expect(user.name, "Open WebUI MUST take the display name from the name claim on every login").toContain(probeFirstName);
      expect(
        user.email,
        mailbox
          ? "Under the mailbox policy the email claim MUST stay the mailbox while the secondary address changes"
          : "Open WebUI MUST take the e-mail from the email claim on every login",
      ).toBe(claimedEmail.toLowerCase());

      await shared.dismissAllOpenModals(page);
      await page
        .getByRole("img", { name: /open\s+user\s+profile\s+menu/i })
        .or(page.getByRole("button", { name: /open\s+user\s+profile\s+menu/i }))
        .first()
        .click();
      await expect(page.getByText(probeFirstName).first(), "the user menu MUST show the synced name").toBeVisible({
        timeout: resolveTimeout(30_000),
      });
      await page.keyboard.press("Escape");

      await shared.expectSignInRequiredAfterLogout(page);
    } finally {
      if (original) {
        const restore = (async () => {
          await rewriteKeycloakUser(biberUsername, (user) => ({
            ...user,
            firstName: original.firstName,
            email: original.email,
            emailVerified: original.emailVerified,
          }));
          await page.context().clearCookies();
          await shared.signInViaDashboardOidc(page, biberUsername, biberPassword, "biber");
          await shared.expectSignInRequiredAfterLogout(page);
        })();
        await Promise.race([
          restore,
          new Promise((_, reject) => setTimeout(() => reject(new Error("restore timed out")), RESTORE_DEADLINE_MS)),
        ]).catch((err) => console.warn(`Restoring the profile of ${biberUsername} failed: ${err}`));
      }
    }
  });
};
