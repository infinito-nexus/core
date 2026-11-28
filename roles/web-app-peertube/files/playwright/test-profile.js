const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { rootAccessToken, peertubeAccountOf } = require("./peertube-api");

exports.register = function (shared) {
  test("biber: OIDC account takes display name and email from the identity provider", async ({ page, request }) => {
    skipUnlessServiceEnabled("sso");
    expect(shared.env.biberFullName, "BIBER_FULL_NAME must be set").toBeTruthy();
    expect(shared.env.biberEmail, "BIBER_EMAIL must be set").toBeTruthy();

    await shared.signIn(page, shared.env.biberUsername, shared.env.biberPassword, "biber");
    await shared.logout(page);

    const accessToken = await rootAccessToken(
      request,
      shared.env.peertubeBaseUrl,
      shared.env.rootUsername,
      shared.env.rootPassword,
    );
    const account = await peertubeAccountOf(request, shared.env.peertubeBaseUrl, accessToken, shared.env.biberUsername);
    expect(
      account.account.displayName,
      "display-name-property MUST read the name claim, not the username",
    ).toBe(shared.env.biberFullName);
    expect(account.email.toLowerCase(), "mail-property MUST read the email claim").toBe(
      shared.env.biberEmail.toLowerCase(),
    );
  });
};
