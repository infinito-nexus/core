const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { apiGetOnion } = require("./personas");

exports.register = function (shared) {
  test("biber: the open gate admits a realm user and the broker writes the name claim as display name", async ({ page, request }) => {
    shared.skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(180_000)); // Keycloak round trip plus the broker's PDS account and profile writes
    expect(shared.env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
    expect(shared.env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();
    expect(shared.env.biberFullName, "BIBER_FULL_NAME must be set").toBeTruthy();

    await shared.loginThroughBrokerAs(page, shared.env.biberUsername, shared.env.biberPassword);

    const did = await page.evaluate(
      () => JSON.parse(localStorage.getItem("BSKY_STORAGE") || "{}").session?.currentAccount?.did || "",
    );
    expect(did, "the broker handoff MUST carry biber's DID, so the open gate admitted biber").toBeTruthy();

    const response = await apiGetOnion(
      request,
      `${shared.env.pdsBaseUrl}/xrpc/com.atproto.repo.getRecord?repo=${encodeURIComponent(did)}&collection=app.bsky.actor.profile&rkey=self`,
      { timeout: resolveTimeout(30_000) },
    );
    expect(response.status(), `PDS getRecord must return 200 (got body: ${await response.text()})`).toBe(200);
    expect(
      (await response.json()).value.displayName,
      "the broker MUST write the name claim as displayName of app.bsky.actor.profile",
    ).toBe(shared.env.biberFullName);
  });
};
