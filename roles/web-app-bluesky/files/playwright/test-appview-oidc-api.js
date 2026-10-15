const { test } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { brokerAccessJwt, expectPdsProxiesAppView } = require("./_appview");

exports.register = function (shared) {
  test("OIDC: PDS proxies Following and Notifications to the AppView for the broker session", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(480_000));

    await shared.loginThroughBroker(page);
    const accessJwt = await brokerAccessJwt(page);
    await expectPdsProxiesAppView(page.request, shared.env.pdsBaseUrl, accessJwt);
  });
};
