const { randomUUID } = require("node:crypto");
const { test, expect } = require("@playwright/test");
const { apiFetchOnion } = require("./personas");
const { resolveTimeout } = require("./timeouts");

const CLIENT = 'MediaBrowser Client="playwright", Device="spec", DeviceId="infinito-spec", Version="1.0.0"';

exports.register = function (shared) {
  test("administrator: native local login (break-glass) lands on the Jellyfin home", async ({ page }) => {
    test.setTimeout(resolveTimeout(60_000));
    expect(shared.env.adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
    expect(shared.env.adminNativePassword, "ADMIN_NATIVE_PASSWORD must be set").toBeTruthy();

    await shared.signInViaLocal(page, shared.env.adminUsername, shared.env.adminNativePassword, "administrator-native");

    await expect(page.locator("body")).toContainText(/home|library|media|jellyfin|dashboard/i, { timeout: resolveTimeout(60_000) });

    await shared.logout(page, "administrator-native");
  });

  test("administrator: the server takes the password of the administrator user and refuses any other", async ({ page }) => {
    const authenticate = (password) =>
      apiFetchOnion(page.request, `${shared.env.jellyfinBaseUrl}/Users/AuthenticateByName`, {
        method: "POST",
        headers: { "X-Emby-Authorization": CLIENT },
        data: { Username: shared.env.adminUsername, Pw: password },
      });
    expect((await authenticate(randomUUID())).ok(), "a password other than the administrator's must be refused").toBe(false);
    expect((await authenticate(shared.env.adminNativePassword)).status(), "the password of the administrator user must sign in").toBe(200);
  });
};
