const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const {
  gotoOnion,
  installCspViolationObserver,
  keycloakAdminAddUserToGroup,
  keycloakRemoveUserFromGroupViaRest,
} = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { networkTenants, canonicalMainOrigin } = require("./network-sites");

const MULTISITE_SKIP_REASON =
  "WORDPRESS_MULTISITE_ENABLED=false; Multisite RBAC scenarios run only when the role flag is true";

function primaryTenant(shared) {
  return networkTenants(shared.env).primary;
}

function ownSiteOrigin(shared, domain) {
  return `${new URL(canonicalMainOrigin(shared.env)).protocol}//${domain}`;
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

function siteOwnerDomain(shared) {
  return `${shared.env.biberUsername}.${shared.env.siteOwnerParentDomain}`.toLowerCase();
}

async function networkSiteRow(page, shared, domain) {
  await gotoOnion(page, `${shared.env.wpBaseUrl}/wp-admin/network/sites.php`, { waitUntil: "domcontentloaded" });
  await expect(page.locator("#the-list"), "the network admin MUST list the sites of the network").toBeVisible({
    timeout: resolveTimeout(30_000),
  });
  return page.locator("#the-list tr").filter({
    has: page.locator("a.edit", { hasText: new RegExp(`^\\s*${escapeRegExp(domain)}\\s*$`, "i") }),
  });
}

async function networkSiteId(page, row) {
  const href = await row.locator("a.edit").first().getAttribute("href");
  return new URL(href, page.url()).searchParams.get("id");
}

async function deleteNetworkSite(page, shared, domain) {
  const row = await networkSiteRow(page, shared, domain);
  if ((await row.count()) === 0) {
    return;
  }
  await row.first().hover();
  await row.first().locator(".row-actions span.delete a").click();
  await page.locator("input#submit").click();
  await page.waitForURL((url) => url.searchParams.has("updated"), { timeout: resolveTimeout(30_000) });
  await expect(
    await networkSiteRow(page, shared, domain),
    `the network MUST list no site on ${domain} once it is deleted`
  ).toHaveCount(0, { timeout: resolveTimeout(30_000) });
}

async function cleanUpOwnSite(browser, shared, domain) {
  const cleanupBudgetMs = resolveTimeout(120_000);
  let cleanupTimer;
  await Promise.race([
    withWordPressLogin(browser, shared, shared.env.adminUsername, shared.env.adminPassword, (page) =>
      deleteNetworkSite(page, shared, domain)
    ),
    new Promise((_, reject) => {
      cleanupTimer = setTimeout(() => reject(new Error(`deleting ${domain} exceeded ${cleanupBudgetMs} ms`)), cleanupBudgetMs);
    }),
  ])
    .catch((err) => console.warn(`Cleanup of biber's own site ${domain} failed: ${err}`))
    .finally(() => clearTimeout(cleanupTimer));
}

async function expectOwnSiteServed(browser, shared, domain, archived) {
  const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const page = await ctx.newPage();
    const url = `${ownSiteOrigin(shared, domain)}/`;
    const response = await gotoOnion(page, url, { waitUntil: "domcontentloaded" });
    if (archived) {
      expect(response && response.status(), `the archived ${domain} MUST answer 410 Gone`).toBe(410);
      return;
    }
    expect(response && response.status(), `${domain} MUST serve its own site`).toBeLessThan(400);
    await expect(page, `${domain} MUST carry its own site title`).toHaveTitle(new RegExp(escapeRegExp(domain), "i"));
  } finally {
    await ctx.close().catch(() => {});
  }
}

async function expectOwnSiteAdministeredWithoutSsoSettings(page, shared, domain) {
  const ownAdmin = `${ownSiteOrigin(shared, domain)}/wp-admin/`;
  const dashboard = await gotoOnion(page, ownAdmin, { waitUntil: "domcontentloaded" });
  expect(dashboard && dashboard.status(), `the main-site sign-in MUST open the admin of ${domain}`).toBeLessThan(400);
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(30_000), message: `Expected to stay on ${ownAdmin}` })
    .toContain(`//${domain}/wp-admin`);
  await expect(page.locator("#adminmenu"), `biber MUST administer ${domain}`).toBeVisible({
    timeout: resolveTimeout(30_000),
  });
  await expect(
    page.locator("#adminmenu a[href*='page=openid-connect-generic-settings']"),
    `the admin menu of ${domain} MUST NOT offer the SSO settings`
  ).toHaveCount(0);
  const settings = await gotoOnion(page, `${ownAdmin}options-general.php?page=openid-connect-generic-settings`, {
    waitUntil: "domcontentloaded",
  });
  expect(settings && settings.status(), `biber MUST NOT open the SSO settings of ${domain}`).toBe(403);
}

async function expectOwnSiteSsoSettingsUnwritable(page, shared, domain) {
  const ownOrigin = ownSiteOrigin(shared, domain);
  const nonce = await page.request.get(`${ownOrigin}/wp-admin/admin-ajax.php?action=rest-nonce`);
  const nonceBody = (await nonce.text()).trim();
  expect(
    nonce.status(),
    `biber MUST receive a REST nonce on ${domain}; ${nonce.url()} answered ${nonceBody.slice(0, 200)}`
  ).toBe(200);
  const rest = await page.request.get(`${ownOrigin}/wp-json/wp/v2/settings`, {
    headers: { "X-WP-Nonce": nonceBody },
  });
  expect(rest.status(), `biber MUST read the REST settings of ${domain}`).toBe(200);
  expect(
    Object.keys(await rest.json()),
    `the REST settings of ${domain} MUST NOT expose the SSO settings`
  ).not.toContain("openid_connect_generic_settings");
  const settingsPage = await page.request.get(
    `${ownOrigin}/wp-admin/options-general.php?page=openid-connect-generic-settings`
  );
  const formNonce = (await settingsPage.text()).match(/name=["']_wpnonce["'][^>]*\bvalue=["']([^"']+)["']/i);
  const post = await page.request.post(`${ownOrigin}/wp-admin/options.php`, {
    form: {
      option_page: "openid_connect_generic_settings-group",
      action: "update",
      _wpnonce: formNonce ? formNonce[1] : "",
      "openid_connect_generic_settings[client_id]": "infinito-site-owner-probe",
    },
    maxRedirects: 0,
  });
  expect(
    post.status(),
    `options.php on ${domain} MUST refuse the SSO settings with the nonce their settings page hands out`
  ).toBe(403);
}

async function expectOwnSiteLoginRoutedToMain(browser, shared, domain) {
  const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const page = await ctx.newPage();
    await gotoOnion(page, `${ownSiteOrigin(shared, domain)}/wp-login.php`, {
      waitUntil: "domcontentloaded",
    });
    await expect
      .poll(() => page.url(), {
        timeout: resolveTimeout(60_000),
        message: `the sign-in on ${domain} MUST reach the Keycloak authorize endpoint`,
      })
      .toMatch(/\/protocol\/openid-connect\/auth/i);
    const redirectUri = new URL(page.url()).searchParams.get("redirect_uri") || "";
    expect(
      new URL(redirectUri).host,
      `the sign-in on ${domain} MUST return to the main site, whose redirect URI Keycloak knows`
    ).toBe(new URL(canonicalMainOrigin(shared.env)).host);
    const clientId = new URL(page.url()).searchParams.get("client_id");
    expect(clientId, `the sign-in on ${domain} MUST name the client`).toBeTruthy();
    return clientId;
  } finally {
    await ctx.close().catch(() => {});
  }
}

async function expectOwnSiteListed(page, shared, domain, listed) {
  await gotoOnion(page, `${shared.env.wpBaseUrl}/wp-admin/my-sites.php`, { waitUntil: "domcontentloaded" });
  const link = page.locator(`#wpbody a[href*="//${domain}"]`);
  if (listed) {
    await expect(link.first(), `biber's My Sites MUST link ${domain}`).toBeVisible({ timeout: resolveTimeout(30_000) });
    return;
  }
  await expect(page.locator("#wpbody"), "biber MUST open My Sites").toBeVisible({ timeout: resolveTimeout(30_000) });
  await expect(link, `biber's My Sites MUST NOT link the archived ${domain}`).toHaveCount(0);
}

async function withWordPressLoginOn(browser, shared, baseUrl, username, password, body) {
  const ctx = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1440, height: 1100 },
  });
  try {
    const page = await ctx.newPage();
    await installCspViolationObserver(page);
    await shared.wpAdminLoginViaOidc(page, baseUrl, username, password);
    await body(page);
    await shared.wpSignOut(page, baseUrl);
  } finally {
    await ctx.close().catch(() => {});
  }
}

function withWordPressLogin(browser, shared, username, password, body) {
  return withWordPressLoginOn(browser, shared, shared.env.wpBaseUrl, username, password, body);
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
    const { primary, children } = networkTenants(shared.env);
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

  test("biber: the global editor group grants WordPress Editor on every site without a site-specific group and leaving it takes Editor away (multisite)", async ({
    browser,
  }) => {
    skipUnlessServiceEnabled("sso");
    test.skip(!shared.env.multisiteEnabled, MULTISITE_SKIP_REASON);
    test.setTimeout(resolveTimeout(360_000));
    const { primary, children } = networkTenants(shared.env);
    const domains = [primary, ...children];
    const groupPath = shared.rbacGroupPath({ role: "editor" });
    const asBiber = (body) =>
      withWordPressLogin(browser, shared, shared.env.biberUsername, shared.env.biberPassword, body);
    const asAdmin = (body) =>
      withWordPressLogin(browser, shared, shared.env.adminUsername, shared.env.adminPassword, body);

    await withBiberInGroup(browser, shared, groupPath, async (leaveGroup) => {
      await asBiber((page) => expectNoSuperAdmin(page, shared, `biber in ${groupPath}`));
      await asAdmin(async (page) => {
        for (const domain of domains) {
          const rows = await siteUserRows(page, shared, domain);
          await expect(rows.first(), `biber in ${groupPath} MUST be a member of ${domain}`).toBeVisible({
            timeout: resolveTimeout(30_000),
          });
          await expect(
            rows.first().locator("td.column-role"),
            `biber in ${groupPath} MUST hold Editor on ${domain}`
          ).toContainText("Editor");
        }
      });

      await leaveGroup();
      await asBiber((page) => expectNoSuperAdmin(page, shared, `biber after leaving ${groupPath}`));
      await asAdmin(async (page) => {
        for (const domain of domains) {
          const rows = await siteUserRows(page, shared, domain);
          await expect(
            rows.filter({ has: page.locator("td.column-role", { hasText: "Editor" }) }),
            `biber after leaving ${groupPath} MUST NOT hold Editor on ${domain}`
          ).toHaveCount(0);
        }
      });
    });
  });

  test("biber: joining site-owner creates biber's own site on the first login, leaving archives it and rejoining restores it (multisite)", async ({
    browser,
  }) => {
    skipUnlessServiceEnabled("sso");
    test.skip(!shared.env.multisiteEnabled, MULTISITE_SKIP_REASON);
    test.skip(
      !shared.env.siteOwnerEnabled,
      "WORDPRESS_SITE_OWNER_ENABLED=false; the variant declares no domains.served entry for site-owner"
    );
    test.setTimeout(resolveTimeout(900_000));
    expect(shared.env.siteOwnerParentDomain, "WORDPRESS_SITE_OWNER_PARENT_DOMAIN must be set").toBeTruthy();
    const groupPath = shared.rbacGroupPath({ siteOwner: true });
    const domain = siteOwnerDomain(shared);
    const asAdmin = (body) =>
      withWordPressLogin(browser, shared, shared.env.adminUsername, shared.env.adminPassword, body);
    const asBiber = (body) =>
      withWordPressLogin(browser, shared, shared.env.biberUsername, shared.env.biberPassword, body);
    let siteId = null;

    try {
      await asAdmin((page) => deleteNetworkSite(page, shared, domain));

      await withBiberInGroup(browser, shared, groupPath, async (leaveGroup) => {
        await asBiber((page) => expectOwnSiteListed(page, shared, domain, true));
        await asBiber((page) => expectOwnSiteListed(page, shared, domain, true));
        await asAdmin(async (page) => {
          const row = await networkSiteRow(page, shared, domain);
          await expect(row, `two logins of biber in ${groupPath} MUST leave exactly one site on ${domain}`).toHaveCount(1, {
            timeout: resolveTimeout(30_000),
          });
          await expect(row, `the site on ${domain} MUST NOT be archived while biber is in ${groupPath}`).not.toHaveClass(
            /\bsite-archived\b/
          );
          siteId = await networkSiteId(page, row);
          const biberRows = await siteUserRows(page, shared, domain);
          await expect(
            biberRows.first().locator("td.column-role"),
            `biber MUST administer the own site ${domain}`
          ).toContainText("Administrator");
        });
        if (shared.env.siteOwnerWildcard) {
          await expectOwnSiteServed(browser, shared, domain, false);
        }

        await leaveGroup();
        await asBiber((page) => expectOwnSiteListed(page, shared, domain, false));
        await asAdmin(async (page) => {
          const row = await networkSiteRow(page, shared, domain);
          await expect(row, `leaving ${groupPath} MUST keep the site on ${domain}`).toHaveCount(1, {
            timeout: resolveTimeout(30_000),
          });
          expect(await networkSiteId(page, row), `leaving ${groupPath} MUST keep site ${siteId} itself`).toBe(siteId);
          await expect(row, `leaving ${groupPath} MUST archive the site on ${domain}`).toHaveClass(/\bsite-archived\b/);
        });
        if (shared.env.siteOwnerWildcard) {
          await expectOwnSiteServed(browser, shared, domain, true);
        }
      });

      await withBiberInGroup(browser, shared, groupPath, async () => {
        await asBiber((page) => expectOwnSiteListed(page, shared, domain, true));
        if (shared.env.siteOwnerWildcard) {
          await expectOwnSiteServed(browser, shared, domain, false);
        }
        await asAdmin(async (page) => {
          const row = await networkSiteRow(page, shared, domain);
          await expect(row, `rejoining ${groupPath} MUST keep exactly one site on ${domain}`).toHaveCount(1, {
            timeout: resolveTimeout(30_000),
          });
          expect(await networkSiteId(page, row), `rejoining ${groupPath} MUST restore site ${siteId}`).toBe(siteId);
          await expect(row, `rejoining ${groupPath} MUST restore the archived site on ${domain}`).not.toHaveClass(
            /\bsite-archived\b/
          );
        });
      });
    } finally {
      await cleanUpOwnSite(browser, shared, domain);
    }
  });

  test("biber: the own site keeps its SSO settings out of reach and routes its sign-in to the main site (multisite)", async ({
    browser,
  }) => {
    skipUnlessServiceEnabled("sso");
    test.skip(!shared.env.multisiteEnabled, MULTISITE_SKIP_REASON);
    test.skip(
      !shared.env.siteOwnerEnabled || !shared.env.siteOwnerWildcard,
      "WORDPRESS_SITE_OWNER_ENABLED or WORDPRESS_SITE_OWNER_WILDCARD is false; only a wildcard certificate serves an own site created at sign-in"
    );
    test.setTimeout(resolveTimeout(600_000));
    const groupPath = shared.rbacGroupPath({ siteOwner: true });
    const domain = siteOwnerDomain(shared);
    const asBiberOnOwnNetwork = (body) =>
      withWordPressLoginOn(
        browser,
        shared,
        canonicalMainOrigin(shared.env),
        shared.env.biberUsername,
        shared.env.biberPassword,
        body
      );

    try {
      await withBiberInGroup(browser, shared, groupPath, async () => {
        await asBiberOnOwnNetwork((page) => expectOwnSiteAdministeredWithoutSsoSettings(page, shared, domain));
        const clientId = await expectOwnSiteLoginRoutedToMain(browser, shared, domain);
        await asBiberOnOwnNetwork((page) => expectOwnSiteSsoSettingsUnwritable(page, shared, domain));
        expect(
          await expectOwnSiteLoginRoutedToMain(browser, shared, domain),
          `the options.php POST of biber MUST leave the SSO client of ${domain} unchanged`
        ).toBe(clientId);
      });
    } finally {
      await cleanUpOwnSite(browser, shared, domain);
    }
  });
};
