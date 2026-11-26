const { test, expect } = require("@playwright/test");

const { apiFetchOnion, apiGetOnion, gotoOnion } = require("./personas");
const { resolveTimeout } = require("./timeouts");
const {
  KEYCLOAK_LOGIN,
  biberTokens,
  confirmLogoutOnThisDevice,
  durationMs,
  endEveryOtherSession,
  endTokenSession,
  expectGatedAppAsksForLogin,
  expectGatedSession,
  expectSynapseSession,
  forgedLogoutToken,
  gatedAppSessions,
  logoutEnv,
  openContext,
  signInToGatedApp,
  signInToSynapse,
} = require("./logout-flow");

const FOREIGN_CLIENT = "infinito-foreign-client";
const FOREIGN_REALM = "infinito-foreign";

/**
 * Return the probes every back-channel endpoint must refuse.
 *
 * Args:
 *   target: one entry of BACKCHANNEL_TARGETS_JSON.
 *   keycloakSigned: a token set Keycloak issued biber through the shared client.
 */
function refusedLogoutTokens(target, keycloakSigned) {
  return [
    ["signed with a foreign key", forgedLogoutToken(target.client_id)],
    [
      "from a foreign issuer",
      forgedLogoutToken(target.client_id, { iss: `${new URL(logoutEnv.issuerUrl).origin}/realms/${FOREIGN_REALM}` }),
    ],
    ["for another client", forgedLogoutToken(FOREIGN_CLIENT)],
    ["signed by Keycloak for the shared client, without the events claim", keycloakSigned.id_token],
  ];
}

/**
 * Args:
 *   request: the API request context of the page whose proxy session is
 *     probed; it sends and updates that page's cookies.
 *   url: an oauth2-proxy-gated URL of one network.
 *
 * Returns:
 *   The status the oauth2-proxy session check of that network answers with:
 *   202 while the gate holds a session of the page, 401 once it holds none.
 */
async function proxySessionStatus(request, url) {
  const response = await apiGetOnion(request, `${new URL(url).origin}/oauth2/auth`, {
    maxRedirects: 0,
    timeout: resolveTimeout(30_000),
  });
  return response.status();
}

/**
 * Args:
 *   page: a page of the context whose proxy session is probed.
 *   url: an oauth2-proxy-gated URL of one network.
 *   status: 202 for a session the gate holds, 401 for none.
 *   timeout: how long the gate may take to answer with that status.
 */
async function expectProxySession(page, url, status, timeout) {
  await expect
    .poll(() => proxySessionStatus(page.request, url), {
      timeout,
      intervals: [1_000, 2_000],
      message: `${url}: the oauth2-proxy session check must answer ${status}`,
    })
    .toBe(status);
}

/**
 * Args:
 *   page: a page of the context signed in to Keycloak.
 *   url: an oauth2-proxy-gated URL of one network.
 */
async function signInBehindProxy(page, url) {
  const origin = new URL(url).origin;
  await gotoOnion(page, `${origin}/oauth2/start?rd=%2F`);
  await page.waitForURL((landed) => landed.origin === origin, { timeout: resolveTimeout(120_000) });
  await expectProxySession(page, url, 202, resolveTimeout(30_000));
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
        logoutEnv.backchannelTargets.length === 0,
        "BACKCHANNEL_TARGETS_JSON is empty: no application with its own back-channel client is deployed",
      );
    });

    test("logout-backchannel: a forged or foreign logout token ends no session", async ({ browser }) => {
      test.setTimeout(resolveTimeout(300_000));
      const context = await openContext(browser);
      try {
        const page = await context.newPage();
        const synapse = logoutEnv.synapseUrl ? await signInToSynapse(page) : "";
        const keycloakSigned = await biberTokens(context.request);
        try {
          expect(keycloakSigned.id_token, "Keycloak must hand biber an ID token to replay as a logout token").toBeTruthy();
          for (const target of logoutEnv.backchannelTargets) {
            for (const [kind, token] of refusedLogoutTokens(target, keycloakSigned)) {
              const response = await apiFetchOnion(context.request, target.url, {
                method: "POST",
                form: { logout_token: token },
                maxRedirects: 0,
                timeout: resolveTimeout(30_000),
              });
              if (target.sealed_url) {
                expect(response.status(), `${target.id}: the logout gate must refuse a token ${kind}`).toBe(400);
                continue;
              }
              expect(response.status(), `${target.id}: a token ${kind} must be refused`).toBeGreaterThanOrEqual(400);
              expect(response.status(), `${target.id}: a token ${kind} is a client error, not a crash`).toBeLessThan(500);
            }
          }
        } finally {
          await endTokenSession(context.request, keycloakSigned.refresh_token);
        }
        if (synapse) {
          await expectSynapseSession(context.request, synapse, 200);
          await confirmLogoutOnThisDevice(page);
          await expectSynapseSession(context.request, synapse, 401);
        }
      } finally {
        await context.close();
      }
    });

    test("logout-backchannel: a receiver behind the logout gate refuses a request that skips the gate", async ({ browser }) => {
      const gated = logoutEnv.backchannelTargets.filter((target) => target.sealed_url);
      test.skip(gated.length === 0, "no deployed application has its back-channel receiver behind the logout gate");
      const context = await openContext(browser);
      try {
        for (const target of gated) {
          for (const [kind, headers] of [
            ["without the gate key", {}],
            ["with a wrong gate key", { "X-Logout-Gate-Key": "infinito-forged-gate-key" }],
          ]) {
            const response = await apiFetchOnion(context.request, target.sealed_url, {
              method: "POST",
              headers,
              form: { logout_token: forgedLogoutToken(target.client_id) },
              timeout: resolveTimeout(30_000),
            });
            expect(response.status(), `${target.id}: a POST ${kind} must stop at the proxy`).toBe(403);
          }
        }
      } finally {
        await context.close();
      }
    });

    test("logout-backchannel: a Keycloak session ended without the conductor ends every gated app session", async ({ browser }) => {
      const gated = gatedAppSessions();
      test.skip(gated.length === 0, "no deployed application has its back-channel receiver behind the logout gate");
      test.setTimeout(resolveTimeout(900_000));
      const context = await openContext(browser);
      const otherDevice = await openContext(browser);
      try {
        const page = await context.newPage();
        for (const app of gated) {
          await signInToGatedApp(page, app);
        }
        for (const app of gated) {
          await expectGatedSession(page, app, true);
        }
        await endEveryOtherSession(otherDevice.request);
        for (const app of gated) {
          await expectGatedAppAsksForLogin(page, app);
        }
      } finally {
        await context.close();
        await otherDevice.close();
      }
    });

    for (const javaScriptEnabled of [true, false]) {
      test(`logout-backchannel: a clearnet logout ends the sessions on the other network (javaScriptEnabled: ${javaScriptEnabled})`, async ({
        browser,
      }) => {
        test.skip(!logoutEnv.synapseUrl, "MATRIX_SYNAPSE_URL is empty: the network case signs in to Synapse as its back-channel app");
        test.skip(
          logoutEnv.proxyTargetUrls.length < 2,
          "this pass reaches one network only: no oauth2-proxy app that admits every realm user has an onion sibling, or the clearnet pass has no Tor proxy to reach it",
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
          await expectProxySession(
            page,
            logoutEnv.proxyTargetUrls[1],
            401,
            resolveTimeout(durationMs(logoutEnv.cookieRefresh) + 5_000),
          );
          await expectProxyAsksForLogin(page, logoutEnv.proxyTargetUrls[1]);
        } finally {
          await context.close();
        }
      });
    }
  });
};
