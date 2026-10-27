const { test, expect } = require("./onion-test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvQuotedValue, gotoOnion, performKeycloakLogin } = require("./personas");

exports.register = function (shared) {
  test("jitsi: a guest joins a conference on the Jitsi that Element offers", async ({ page, request }) => {
    shared.skipUnlessServiceEnabled("jitsi");
    const jitsiBaseUrl = (decodeDotenvQuotedValue(process.env.JITSI_BASE_URL) || "").replace(/\/+$/, "");
    expect(jitsiBaseUrl, "JITSI_BASE_URL must be set when jitsi is enabled").toBeTruthy();

    const configResponse = await request.get(`${shared.env.elementBaseUrl}/config.json`, {
      failOnStatusCode: false,
      timeout: resolveTimeout(30_000),
    });
    expect(configResponse.status(), "Element /config.json must serve").toBe(200);
    const elementConfig = await configResponse.json();
    expect(elementConfig.jitsi?.preferred_domain, "Element must offer the Jitsi this deployment serves").toBe(new URL(jitsiBaseUrl).host);

    const room = `playwright-matrix-${Date.now()}`;
    const fragment = [
      "config.prejoinConfig.enabled=false",
      "config.startWithAudioMuted=true",
      "config.startWithVideoMuted=true",
      'userInfo.displayName="Playwright"',
    ].join("&");
    const roomUrl = `${jitsiBaseUrl}/${room}#${fragment}`;
    await gotoOnion(page, roomUrl, { waitUntil: "domcontentloaded" });
    if (decodeDotenvQuotedValue(process.env.JITSI_SSO_ENABLED) === "true") {
      const { adminUsername, adminPassword } = shared.env;
      await performKeycloakLogin(page, adminUsername, adminPassword, new URL(jitsiBaseUrl).hostname);
      await gotoOnion(page, roomUrl, { waitUntil: "domcontentloaded" });
    }

    await page.waitForFunction(() => Boolean(window.APP?.conference?.isJoined?.()), null, {
      timeout: resolveTimeout(120_000),
    });
  });
};
