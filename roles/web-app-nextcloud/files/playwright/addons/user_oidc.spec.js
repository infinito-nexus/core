const { test, expect } = require("@playwright/test");
const { apiFetchOnion, decodeDotenvJsonList, gotoOnion, requireDotenvValue } = require("../personas");
const { isOnionTarget, resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const shared = require("../_shared");

// `user_oidc` is the OIDC auth-path plugin selected when sso_oidc_plugin ==
// "user_oidc". Like the other OIDC plugins it has no distinct in-app page; its
// only browser-reachable surface is the login journey. Reuse the shared
// `loginToStandaloneNextcloud` flow (which handles the Keycloak handoff for
// every OIDC flavor) instead of reimplementing OIDC mechanics, and assert that
// an authenticated Nextcloud shell results.
test("addon user_oidc: nextcloud OIDC login surface authenticates", async ({ browser }) => {
  skipUnlessAddonEnabled("user_oidc");
  skipUnlessServiceEnabled("sso");

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    const shellState = await shared.waitForVisibleCandidate(
      page,
      shared.getNextcloudShellCandidates(page),
      resolveTimeout(60_000),
      "Timed out waiting for an authenticated Nextcloud shell after the user_oidc OIDC login flow",
    );
    await expect(shellState.locator).toBeVisible();
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});

/**
 * Return the status of the OCS user endpoint and, when it answers 200, the
 * account the session of the request context is signed in to.
 *
 * Args:
 *   request: the API request context of a browser context.
 *   baseUrl: the Nextcloud base URL of one network.
 */
async function nextcloudAccount(request, baseUrl) {
  const response = await apiFetchOnion(request, new URL("ocs/v2.php/cloud/user?format=json", baseUrl).toString(), {
    method: "GET",
    headers: { Accept: "application/json", "OCS-APIRequest": "true" },
    maxRedirects: 0,
    timeout: resolveTimeout(30_000),
  });
  return { status: response.status(), data: response.ok() ? (await response.json()).ocs.data : null };
}

test("addon user_oidc: biber signs in to the account biber held before the switch", async ({ browser }) => {
  skipUnlessAddonEnabled("user_oidc");
  skipUnlessServiceEnabled("sso");

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const page = await context.newPage();
    await shared.loginToStandaloneNextcloud(page, shared.env.biberUsername, shared.env.biberPassword);
    const account = await nextcloudAccount(context.request, shared.env.nextcloudBaseUrl);
    expect(account.status, "biber's user_oidc session must answer the OCS user endpoint").toBe(200);
    expect(account.data.id, "user_oidc must keep biber's user id instead of hashing a new one").toBe(shared.env.biberUsername);
    if (shared.env.nextcloudLdapEnabled) {
      expect(account.data.backend, "with LDAP, user_oidc must sign biber in to the existing LDAP account").toBe("LDAP");
    }
  } finally {
    await context.close().catch(() => {});
  }
});

for (const javaScriptEnabled of [true, false]) {
  test(`addon user_oidc: a logout on one network ends the Nextcloud session on every network (javaScriptEnabled: ${javaScriptEnabled})`, async ({
    browser,
  }) => {
    skipUnlessAddonEnabled("user_oidc");
    skipUnlessServiceEnabled("sso");
    const nextcloudUrls = decodeDotenvJsonList(process.env.NEXTCLOUD_URLS_JSON, "NEXTCLOUD_URLS_JSON");
    test.skip(
      !isOnionTarget() || nextcloudUrls.length < 2,
      "only the onion pass reaches Nextcloud on the clearnet and the onion network: the clearnet pass has no Tor proxy, or Nextcloud has no onion sibling",
    );
    test.setTimeout(resolveTimeout(600_000));
    const keycloakLogoutUrl = requireDotenvValue(process.env.KEYCLOAK_LOGOUT_URL, "KEYCLOAK_LOGOUT_URL");

    const signIn = await browser.newContext({ ignoreHTTPSErrors: true });
    let logout;
    try {
      const page = await signIn.newPage();
      for (const url of nextcloudUrls) {
        await shared.loginToStandaloneNextcloud(page, shared.env.biberUsername, shared.env.biberPassword, url);
        const account = await nextcloudAccount(signIn.request, url);
        expect(account.status, `${url}: biber must be signed in before the logout`).toBe(200);
      }

      logout = await browser.newContext({
        ignoreHTTPSErrors: true,
        javaScriptEnabled,
        storageState: await signIn.storageState(),
      });
      const logoutPage = await logout.newPage();
      await gotoOnion(logoutPage, keycloakLogoutUrl);
      await logoutPage.locator("#kc-logout").click({ timeout: resolveTimeout(30_000) });
      await logoutPage.waitForLoadState("load", { timeout: resolveTimeout(60_000) });

      for (const url of nextcloudUrls) {
        await expect
          .poll(async () => (await nextcloudAccount(signIn.request, url)).status, {
            timeout: resolveTimeout(60_000),
            message: `${url}: Keycloak's back-channel logout must end the Nextcloud session, so the next request asks for a login`,
          })
          .toBe(401);
      }
    } finally {
      await logout?.close().catch(() => {});
      await signIn.close().catch(() => {});
    }
  });
}
