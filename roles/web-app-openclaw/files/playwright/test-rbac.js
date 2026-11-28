const { test, expect } = require("./onion-test");

const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const {
  decodeDotenvQuotedValue,
  gotoOnion,
  keycloakAdminAddUserToGroup,
  keycloakRemoveUserFromGroupViaRest,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  requireDotenvValue,
} = require("./personas");

const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME || "");
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD || "");
const keycloakBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.KEYCLOAK_BASE_URL, "KEYCLOAK_BASE_URL"));
const realmName = requireDotenvValue(process.env.KEYCLOAK_REALM_NAME, "KEYCLOAK_REALM_NAME");
const superAdminUsername = decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME || "");
const superAdminPassword = decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD || "");
const mcpGroupPath = decodeDotenvQuotedValue(process.env.RBAC_MCP_GROUP_PATH || "");

const CLEANUP_TIMEOUT_MS = 30_000;
const PAIRING_PROBE_MS = 5_000;

function withDeadline(promise, label) {
  return Promise.race([
    promise,
    new Promise((_, reject) => setTimeout(() => reject(new Error(`${label} timed out`)), CLEANUP_TIMEOUT_MS)),
  ]);
}

async function signInAsBiber(page, baseUrl) {
  await gotoOnion(page, `${baseUrl}/`);
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "the OAuth2 proxy must hand biber to Keycloak" })
    .toContain("openid-connect/auth");
  await performKeycloakLoginForm(page, biberUsername, biberPassword);
}

async function removeBiberFromGroup(browser, groupPath) {
  const cleanup = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    await withDeadline(
      keycloakRemoveUserFromGroupViaRest(
        cleanup.request,
        keycloakBaseUrl,
        realmName,
        superAdminUsername,
        superAdminPassword,
        groupPath,
        biberUsername,
      ),
      `removing biber from ${groupPath}`,
    );
  } catch (err) {
    console.warn(`Cleanup removal of biber from ${groupPath} failed: ${err}`);
  } finally {
    await cleanup.close().catch(() => {});
  }
}

exports.register = function (shared) {
  test("administrator: the gateway authenticates the allowlisted administrator from the proxy identity, without the gateway token", async ({
    page,
  }) => {
    skipUnlessServiceEnabled("sso");
    expect(shared.env.trustedProxy, "OPENCLAW_TRUSTED_PROXY_ENABLED must be true while the sso service is enabled").toBe(true);
    test.setTimeout(resolveTimeout(120_000)); // Keycloak round trip through the OAuth2 proxy plus a gateway handshake

    await shared.openGate(page);
    await expect(
      page.locator(`${shared.GATE} .login-gate__secret-row input`).first(),
      "the gateway token field MUST stay empty, so only the proxy identity can authenticate this browser",
    ).toHaveValue("");
    await shared.connectGate(page);
    await expect(
      page.locator(`${shared.GATE} .login-gate__failure`),
      "a pairing prompt is what the gateway answers once it authenticated the administrator; an auth failure means the secret proxy header or the identity header is wrong",
    ).toHaveAttribute("data-kind", "pairing-required", { timeout: resolveTimeout(60_000) });
  });

  test("administrator: a paired browser reaches the Control UI shell through the proxy identity alone", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    expect(shared.env.trustedProxy, "OPENCLAW_TRUSTED_PROXY_ENABLED must be true while the sso service is enabled").toBe(true);
    test.setTimeout(resolveTimeout(120_000)); // Keycloak round trip through the OAuth2 proxy plus a gateway handshake

    test.skip(
      !(await shared.openDashboard(page, "/overview", PAIRING_PROBE_MS)),
      "no browser identity an operator approved with `openclaw devices approve` is stored for this run (see TODO.md, Dashboard tests)",
    );
    await expect(
      page.locator("openclaw-app-shell"),
      "the Control UI MUST connect with the proxy identity and the paired device, without any gateway token",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });
  });

  test("biber: the OAuth2 proxy refuses a persona holding none of the admitted groups", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(120_000)); // Keycloak round trip through the OAuth2 proxy
    expect(biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
    expect(biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();

    await signInAsBiber(page, shared.env.baseUrl);

    await expect(
      page.locator("openclaw-app"),
      "biber reached the Control UI; meta/services.yml admits only the administrator and mcp groups and biber holds neither",
    ).toHaveCount(0, { timeout: resolveTimeout(30_000) });
    await expect(
      page.locator("body"),
      "the page is neither the Control UI nor a recognisable denial; the proxy may have changed its rejection wording",
    ).toContainText(/403|forbidden|permission|unauthorized|access denied/i);
  });

  test("biber: the gateway authenticates a member who joined an admitted group after the deploy", async ({ browser }) => {
    skipUnlessServiceEnabled("sso");
    expect(shared.env.trustedProxy, "OPENCLAW_TRUSTED_PROXY_ENABLED must be true while the sso service is enabled").toBe(true);
    test.setTimeout(resolveTimeout(240_000)); // Keycloak group change plus a Keycloak round trip and a gateway handshake
    expect(mcpGroupPath, "RBAC_MCP_GROUP_PATH must be set").toBeTruthy();
    expect(superAdminUsername, "SUPER_ADMIN_USERNAME must be set").toBeTruthy();
    expect(superAdminPassword, "SUPER_ADMIN_PASSWORD must be set").toBeTruthy();

    const admin = await browser.newContext({ ignoreHTTPSErrors: true });
    let joined = false;
    try {
      joined = await keycloakAdminAddUserToGroup(
        admin.request,
        keycloakBaseUrl,
        realmName,
        mcpGroupPath,
        biberUsername,
        superAdminUsername,
        superAdminPassword,
      );
      const context = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        const page = await context.newPage();
        await signInAsBiber(page, shared.env.baseUrl);
        await expect(
          page.locator("openclaw-app"),
          "the mcp group MUST pass the OAuth2 proxy, otherwise this scenario proves nothing about the gateway",
        ).toBeAttached({ timeout: resolveTimeout(60_000) });
        await expect(page.locator(shared.GATE)).toBeVisible({ timeout: resolveTimeout(60_000) });
        await shared.connectGate(page);
        await expect(
          page.locator(`${shared.GATE} .login-gate__failure`),
          "the gateway MUST authenticate a member of an admitted group without a redeploy; a pairing prompt is its answer to an authenticated browser",
        ).toHaveAttribute("data-kind", "pairing-required", { timeout: resolveTimeout(60_000) });
      } finally {
        await context.close().catch(() => {});
      }
    } finally {
      await admin.close().catch(() => {});
      if (joined) {
        await removeBiberFromGroup(browser, mcpGroupPath);
      }
    }
  });
};
