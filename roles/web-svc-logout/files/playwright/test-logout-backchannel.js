const { test, expect } = require("@playwright/test");

const { apiFetchOnion, gotoOnion } = require("./personas");
const { resolveTimeout } = require("./timeouts");
const {
  confirmLogoutOnThisDevice,
  durationMs,
  expectSynapseSession,
  forgedLogoutToken,
  logoutEnv,
  openContext,
  signInToSynapse,
} = require("./logout-flow");

const KEYCLOAK_LOGIN = "input[name='username'], input#username";

/**
 * Args:
 *   page: a page of the context signed in to Keycloak.
 *   url: an oauth2-proxy-gated URL of one network.
 */
async function signInBehindProxy(page, url) {
  const origin = new URL(url).origin;
  await gotoOnion(page, url);
  await page.waitForURL((landed) => landed.origin === origin, { timeout: resolveTimeout(120_000) });
}

/**
 * Args:
 *   page: a page of the context whose proxy session should be gone.
 *   url: an oauth2-proxy-gated URL of one network.
 */
async function expectProxyAsksForLogin(page, url) {
  const response = await gotoOnion(page, url);
  expect(response ? response.status() : 0, `${url}: an ended proxy session must not answer 5xx`).toBeLessThan(500);
  await expect(page.locator(KEYCLOAK_LOGIN).first(), `${url}: the proxy must hand over to the Keycloak login`).toBeVisible({
    timeout: resolveTimeout(60_000),
  });
}

exports.register = function () {
  test.describe("logout-backchannel", () => {
    test.describe.configure({ mode: "serial" });

    test.beforeEach(() => {
      test.skip(
        logoutEnv.backchannelTargets.length === 0 || !logoutEnv.synapseUrl,
        "BACKCHANNEL_TARGETS_JSON and MATRIX_SYNAPSE_URL are empty: no application with its own back-channel client is deployed",
      );
    });

    test("logout-backchannel: a logout token signed with a foreign key ends no session", async ({ browser }) => {
      test.setTimeout(resolveTimeout(300_000)); // one Synapse SSO round trip plus a POST per back-channel endpoint
      const context = await openContext(browser);
      try {
        const page = await context.newPage();
        const synapse = await signInToSynapse(page);
        for (const target of logoutEnv.backchannelTargets) {
          const response = await apiFetchOnion(context.request, target.url, {
            method: "POST",
            form: { logout_token: forgedLogoutToken(target.client_id) },
            timeout: resolveTimeout(30_000),
          });
          expect(response.status(), `${target.id}: a forged logout token must be refused`).toBeGreaterThanOrEqual(400);
          expect(response.status(), `${target.id}: refused as a client error, not a crash`).toBeLessThan(500);
        }
        await expectSynapseSession(context.request, synapse, 200);
        await confirmLogoutOnThisDevice(page);
        await expectSynapseSession(context.request, synapse, 401);
      } finally {
        await context.close();
      }
    });

    for (const javaScriptEnabled of [true, false]) {
      test(`logout-backchannel: a clearnet logout ends the sessions on the other network (javaScriptEnabled: ${javaScriptEnabled})`, async ({
        browser,
      }) => {
        test.skip(
          logoutEnv.proxyTargetUrls.length < 2,
          "PROXY_TARGET_URLS_JSON names no oauth2-proxy app with an onion sibling: the node serves one network",
        );
        test.setTimeout(resolveTimeout(900_000)); // three OIDC round trips over two networks plus one cookie_refresh interval
        const context = await openContext(browser, javaScriptEnabled);
        try {
          const page = await context.newPage();
          const synapse = await signInToSynapse(page);
          for (const url of logoutEnv.proxyTargetUrls) {
            await signInBehindProxy(page, url);
          }
          await confirmLogoutOnThisDevice(page);
          await expectSynapseSession(context.request, synapse, 401);
          await page.waitForTimeout(resolveTimeout(durationMs(logoutEnv.cookieRefresh) + 5_000));
          await expectProxyAsksForLogin(page, logoutEnv.proxyTargetUrls[1]);
        } finally {
          await context.close();
        }
      });
    }
  });
};
