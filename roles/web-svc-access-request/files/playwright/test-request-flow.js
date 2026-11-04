const { test, expect } = require("@playwright/test");
const {
  keycloakRemoveUserFromGroupViaRest,
  performKeycloakLoginForm,
} = require("./personas");
const { resolveTimeout } = require("./timeouts");

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
    await admin.locator("#confirm").click();
    await expect(admin.locator("#granted")).toBeVisible();
    await adminContext.close();

    const after = await realmUser(request, env.biberUsername);
    try {
      expect(after.groups).toContain(env.keptRole.path);
      expect(after.groups).not.toContain(env.droppedRole.path);
    } finally {
      await keycloakRemoveUserFromGroupViaRest(request, env.keycloakBaseUrl, env.realmName, env.superAdminUsername, env.superAdminPassword, env.keptRole.path, env.biberUsername);
    }
  });
}

module.exports = { register };
