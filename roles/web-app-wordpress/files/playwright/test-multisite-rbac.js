const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const {
  gotoOnion,
  installCspViolationObserver,
  keycloakAdminAddUserToGroup,
  keycloakRemoveUserFromGroupViaRest,
} = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

const MULTISITE_SKIP_REASON =
  "WORDPRESS_MULTISITE_ENABLED=false; Multisite RBAC scenarios run only when the role flag is true";

function tenants(shared) {
  const all = [
    ...new Set(
      Object.values(JSON.parse(shared.env.rbacGroupMapJson))
        .map((entry) => entry.tenant)
        .filter(Boolean)
    ),
  ];
  const primary = shared.env.canonicalDomain.toLowerCase();
  if (!all.includes(primary)) {
    throw new Error(`WORDPRESS_RBAC_GROUP_MAP carries no per-site group for the primary site ${primary}; tenants: ${all.join(", ")}`);
  }
  return { primary, children: all.filter((tenant) => tenant !== primary) };
}

function primaryTenant(shared) {
  return tenants(shared).primary;
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function siteUserRows(page, shared, domain) {
  await gotoOnion(page, `${shared.env.wpBaseUrl}/wp-admin/network/sites.php`, { waitUntil: "domcontentloaded" });
  const siteLink = page.locator("#the-list a.edit").filter({ hasText: new RegExp(`^\\s*${escapeRegExp(domain)}\\s*$`, "i") });
  await expect(siteLink, `the network MUST list a site whose domain is ${domain}`).toHaveCount(1, {
    timeout: resolveTimeout(30_000),
  });
  await siteLink.click();
  const usersTab = page.locator(".nav-tab-wrapper a[href*='site-users.php']").first();
  await expect(usersTab, `the site ${domain} MUST offer its Users tab`).toBeVisible({ timeout: resolveTimeout(30_000) });
  await usersTab.click();
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(30_000), message: `Expected the Users tab of ${domain}` })
    .toContain("site-users.php");
  return page.locator("#the-list tr").filter({ hasText: new RegExp(shared.env.biberUsername, "i") });
}

async function withWordPressLogin(browser, shared, username, password, body) {
  const ctx = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1440, height: 1100 },
  });
  try {
    const page = await ctx.newPage();
    await installCspViolationObserver(page);
    await shared.wpAdminLoginViaOidc(page, shared.env.wpBaseUrl, username, password);
    await body(page);
    await shared.wpSignOut(page, shared.env.wpBaseUrl);
  } finally {
    await ctx.close().catch(() => {});
  }
}

async function openNetworkAdmin(page, shared) {
  return gotoOnion(page, `${shared.env.wpBaseUrl}/wp-admin/network/`, { waitUntil: "domcontentloaded" });
}

async function expectSuperAdmin(page, shared, who) {
  const response = await openNetworkAdmin(page, shared);
  expect(response && response.status(), `${who} MUST open the network admin`).toBeLessThan(400);
  await expect(
    page.locator("#adminmenu a[href*='sites.php']").first(),
    `${who} MUST see the network Sites menu`
  ).toBeVisible({ timeout: resolveTimeout(30_000) });
}

async function expectNoSuperAdmin(page, shared, who) {
  const response = await openNetworkAdmin(page, shared);
  expect(response && response.status(), `${who} MUST be refused by the network admin`).toBe(403);
}

async function withBiberInGroup(browser, shared, groupPath, body) {
  const reqCtx = await browser.newContext({ ignoreHTTPSErrors: true });
  const { env } = shared;
  const join = () =>
    keycloakAdminAddUserToGroup(
      reqCtx.request,
      env.keycloakBaseUrl,
      env.realmName,
      groupPath,
      env.biberUsername,
      env.superAdminUsername,
      env.superAdminPassword
    );
  const leave = () =>
    keycloakRemoveUserFromGroupViaRest(
      reqCtx.request,
      env.keycloakBaseUrl,
      env.realmName,
      env.superAdminUsername,
      env.superAdminPassword,
      groupPath,
      env.biberUsername
    );
  let joinedByTest = false;
  let leftByTest = false;
  try {
    joinedByTest = await join();
    await body(async () => {
      await leave();
      leftByTest = !joinedByTest;
      joinedByTest = false;
    });
  } finally {
    if (joinedByTest) {
      await leave().catch((err) => console.warn(`Cleanup removal of biber from ${groupPath} failed: ${err}`));
    }
    if (leftByTest) {
      await join().catch((err) => console.warn(`Restoring biber's membership in ${groupPath} failed: ${err}`));
    }
    await reqCtx.close().catch(() => {});
  }
}

exports.register = function (shared) {
  test("administrator: the bootstrap super-admin keeps network admin rights across an OIDC login (multisite)", async ({
    browser,
  }) => {
    skipUnlessServiceEnabled("sso");
    test.skip(!shared.env.multisiteEnabled, MULTISITE_SKIP_REASON);
    test.setTimeout(resolveTimeout(120_000));

    await withWordPressLogin(browser, shared, shared.env.adminUsername, shared.env.adminPassword, (page) =>
      expectSuperAdmin(page, shared, "the bootstrap administrator")
    );
  });

  test("biber: network-administrator group grants WordPress super-admin and leaving it revokes it (multisite)", async ({
    browser,
  }) => {
    skipUnlessServiceEnabled("sso");
    test.skip(!shared.env.multisiteEnabled, MULTISITE_SKIP_REASON);
    test.setTimeout(resolveTimeout(240_000));
    const groupPath = shared.rbacGroupPath({ network: true });

    await withBiberInGroup(browser, shared, groupPath, async (leaveGroup) => {
      await withWordPressLogin(browser, shared, shared.env.biberUsername, shared.env.biberPassword, (page) =>
        expectSuperAdmin(page, shared, `biber in ${groupPath}`)
      );
      await leaveGroup();
      await withWordPressLogin(browser, shared, shared.env.biberUsername, shared.env.biberPassword, (page) =>
        expectNoSuperAdmin(page, shared, `biber after leaving ${groupPath}`)
      );
    });
  });

  test("biber: per-site editor group grants WordPress Editor on the primary site (multisite)", async ({ browser }) => {
    skipUnlessServiceEnabled("sso");
    test.skip(!shared.env.multisiteEnabled, MULTISITE_SKIP_REASON);
    test.setTimeout(resolveTimeout(240_000));
    const groupPath = shared.rbacGroupPath({ role: "editor", tenant: primaryTenant(shared) });

    await withBiberInGroup(browser, shared, groupPath, async () => {
      await withWordPressLogin(browser, shared, shared.env.biberUsername, shared.env.biberPassword, async (page) => {
        await expectNoSuperAdmin(page, shared, `biber in ${groupPath}`);
      });
      await withWordPressLogin(browser, shared, shared.env.adminUsername, shared.env.adminPassword, async (page) => {
        await gotoOnion(page, `${shared.env.wpBaseUrl}/wp-admin/users.php`, { waitUntil: "domcontentloaded" });
        const biberRow = page
          .locator("#the-list tr")
          .filter({ hasText: new RegExp(shared.env.biberUsername, "i") })
          .first();
        await expect(biberRow, "biber MUST be listed on the primary site").toBeVisible({
          timeout: resolveTimeout(30_000),
        });
        await expect(
          biberRow.locator("td.column-role"),
          `biber in ${groupPath} MUST hold Editor on the primary site`
        ).toContainText("Editor");
      });
    });
  });

  test("biber: a child site's editor group grants WordPress Editor on that site and on no other site (multisite)", async ({
    browser,
  }) => {
    skipUnlessServiceEnabled("sso");
    test.skip(!shared.env.multisiteEnabled, MULTISITE_SKIP_REASON);
    test.setTimeout(resolveTimeout(240_000));
    const { primary, children } = tenants(shared);
    expect(children.length, "the Multisite round MUST declare at least one child site").toBeGreaterThan(0);
    const [child, ...others] = children;
    const groupPath = shared.rbacGroupPath({ role: "editor", tenant: child });

    await withBiberInGroup(browser, shared, groupPath, async () => {
      await withWordPressLogin(browser, shared, shared.env.biberUsername, shared.env.biberPassword, (page) =>
        expectNoSuperAdmin(page, shared, `biber in ${groupPath}`)
      );
      await withWordPressLogin(browser, shared, shared.env.adminUsername, shared.env.adminPassword, async (page) => {
        const childRows = await siteUserRows(page, shared, child);
        await expect(childRows.first(), `biber in ${groupPath} MUST be a member of ${child}`).toBeVisible({
          timeout: resolveTimeout(30_000),
        });
        await expect(
          childRows.first().locator("td.column-role"),
          `biber in ${groupPath} MUST hold Editor on ${child}`
        ).toContainText("Editor");
        for (const domain of [primary, ...others]) {
          const rows = await siteUserRows(page, shared, domain);
          await expect(
            rows.filter({ has: page.locator("td.column-role", { hasText: "Editor" }) }),
            `biber in ${groupPath} MUST NOT hold Editor on ${domain}`
          ).toHaveCount(0);
        }
      });
    });
  });
};
