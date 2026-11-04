const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { gotoOnion, keycloakAdminAddUserToGroup, keycloakRemoveUserFromGroupViaRest } = require("../personas");
const shared = require("../_shared");
const { networkTenants } = require("../network-sites");

function childSite() {
  const { primary, children } = networkTenants(shared.env);
  const [child] = children;
  if (!child) {
    throw new Error(`WORDPRESS_RBAC_GROUP_MAP carries no per-site group for a site below the main site ${primary}`);
  }
  return child;
}

test("biber: addon infinito-ai-engine-network: a child site serves no AI Engine MCP route and its site administrator cannot open the AI Engine settings (multisite)", async ({ browser }) => {
  skipUnlessAddonEnabled("infinito-ai-engine-network");
  skipUnlessServiceEnabled("sso");
  test.skip(!shared.env.multisiteEnabled, "WORDPRESS_MULTISITE_ENABLED=false; the guard acts only on a Multisite network");
  test.setTimeout(resolveTimeout(240_000));

  const { env } = shared;
  const child = childSite();
  const childOrigin = `${new URL(env.wpBaseUrl).protocol}//${child}`;
  const groupPath = shared.rbacGroupPath({ role: "administrator", tenant: child });
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  let joinedByTest = false;
  try {
    const index = await context.request.get(`${childOrigin}/wp-json/`);
    expect(index.status(), `${child} MUST answer its REST index`).toBe(200);
    expect((await index.json()).namespaces, `${child} MUST NOT serve the AI Engine MCP routes`).not.toContain("mcp/v1");

    joinedByTest = await keycloakAdminAddUserToGroup(
      context.request,
      env.keycloakBaseUrl,
      env.realmName,
      groupPath,
      env.biberUsername,
      env.superAdminUsername,
      env.superAdminPassword
    );
    const page = await context.newPage();
    await shared.wpAdminLoginViaOidc(page, childOrigin, env.biberUsername, env.biberPassword);
    const settings = await gotoOnion(page, `${childOrigin}/wp-admin/admin.php?page=mwai_settings`, {
      waitUntil: "domcontentloaded",
      timeout: resolveTimeout(60_000),
    });
    expect(
      settings && settings.status(),
      `biber in ${groupPath} administers ${child} but MUST NOT open its AI Engine settings`
    ).toBe(403);
    await expect(page.locator("#mwai-admin-settings"), "the AI Engine settings app MUST NOT render").toHaveCount(0);
    await shared.wpSignOut(page, childOrigin);
  } finally {
    if (joinedByTest) {
      await keycloakRemoveUserFromGroupViaRest(
        context.request,
        env.keycloakBaseUrl,
        env.realmName,
        env.superAdminUsername,
        env.superAdminPassword,
        groupPath,
        env.biberUsername
      ).catch((err) => console.warn(`Cleanup removal of biber from ${groupPath} failed: ${err}`));
    }
    await context.close().catch(() => {});
  }
});
