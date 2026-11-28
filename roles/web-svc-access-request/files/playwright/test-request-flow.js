const { test, expect } = require("@playwright/test");
const {
  keycloakRemoveUserFromGroupViaRest,
  keycloakResolveGroupId,
  performKeycloakLoginForm,
} = require("./personas");
const { resolveTimeout } = require("./timeouts");

/**
 * Return the newest admin event of Keycloak that added the user to the group.
 *
 * Args:
 *   request: an APIRequestContext.
 *   env: the spec env of _shared.js.
 *   member: `{ token, user }` of realmUser, the token being the bootstrap admin's.
 *   groupPath: the group the user joined.
 */
async function newestMembershipGrant(request, env, { token, user }, groupPath) {
  const groupId = await keycloakResolveGroupId(request, env.keycloakBaseUrl, env.realmName, token, groupPath);
  const query = new URLSearchParams({
    operationTypes: "CREATE",
    resourceTypes: "GROUP_MEMBERSHIP",
    resourcePath: `users/${user.id}/groups/${groupId}`,
  });
  const response = await request.get(
    `${env.keycloakBaseUrl}/admin/realms/${encodeURIComponent(env.realmName)}/admin-events?${query}`,
    { headers: { Authorization: `Bearer ${token}` }, timeout: resolveTimeout(30_000) },
  );
  expect(response.status(), "the bootstrap admin must read the realm's admin events").toBe(200);
  const events = await response.json();
  return events.sort((left, right) => right.time - left.time)[0];
}

function register({ env, realmUser }) {
  test("biber requests two roles from the 403 page and holds exactly the role the administrator confirmed", async ({ browser, request }) => {
    test.skip(!env.targetApp, "no deployed restricted application offers two roles");
    test.skip(env.fourEyes, "the four-eyes switch needs a second approver persona");
    test.setTimeout(resolveTimeout(240_000));

    const before = await realmUser(request, env.biberUsername);
    for (const path of [env.keptRole.path, env.droppedRole.path]) {
      if (before.groups.includes(path)) {
        await keycloakRemoveUserFromGroupViaRest(request, env.keycloakBaseUrl, env.realmName, env.superAdminUsername, env.superAdminPassword, path, env.biberUsername);
      }
    }

    const biberContext = await browser.newContext({ ignoreHTTPSErrors: true });
    const biber = await biberContext.newPage();
    await biber.goto(env.targetUrl, { waitUntil: "domcontentloaded" });
    await performKeycloakLoginForm(biber, env.biberUsername, env.biberPassword);
    await expect(biber.locator("#request-access")).toBeVisible({ timeout: resolveTimeout(60_000) });
    await biber.locator("#request-access").click();
    await expect(biber.locator("#application")).toHaveText(env.targetApp, { timeout: resolveTimeout(60_000) });
    await biber.locator(`[id="role-${env.keptRole.id}"]`).check();
    await biber.locator(`[id="role-${env.droppedRole.id}"]`).check();
    await biber.locator("#reason").fill("Playwright: access request round trip");
    await biber.locator("#submit").click();
    await expect(biber.locator("#created, #updated")).toBeVisible();
    const reviewUrl = await biber.locator("#review").getAttribute("href");
    await biberContext.close();

    const adminContext = await browser.newContext({ ignoreHTTPSErrors: true });
    const admin = await adminContext.newPage();
    await admin.goto(reviewUrl, { waitUntil: "domcontentloaded" });
    await performKeycloakLoginForm(admin, env.adminUsername, env.adminPassword);
    await expect(admin.locator("#requester")).toHaveText(env.biberUsername, { timeout: resolveTimeout(60_000) });
    await expect(admin.locator(`tr[data-role="${env.droppedRole.id}"] .diff`)).toHaveText("+");
    await admin.locator(`[id="grant-${env.droppedRole.id}"]`).uncheck();
    const confirmedAt = Date.now();
    await admin.locator("#confirm").click();
    await expect(admin.locator("#granted")).toBeVisible();
    await adminContext.close();

    const after = await realmUser(request, env.biberUsername);
    try {
      expect(after.groups).toContain(env.keptRole.path);
      expect(after.groups).not.toContain(env.droppedRole.path);
      const approver = await realmUser(request, env.adminUsername);
      const grant = await newestMembershipGrant(request, env, after, env.keptRole.path);
      expect(grant, "Keycloak must record the confirmed membership as an admin event").toBeTruthy();
      expect(grant.time, "the admin event must be the one this confirmation caused").toBeGreaterThanOrEqual(confirmedAt);
      expect(grant.authDetails.userId, "the admin event must name the approver who confirmed").toBe(approver.user.id);
    } finally {
      await keycloakRemoveUserFromGroupViaRest(request, env.keycloakBaseUrl, env.realmName, env.superAdminUsername, env.superAdminPassword, env.keptRole.path, env.biberUsername);
    }
  });
}

module.exports = { register };
