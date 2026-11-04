const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceDisabled, skipUnlessServiceEnabled } = require("./service-gating");
const {
  decodeDotenvQuotedValue,
  gotoOnion,
  normalizeBaseUrl,
  performKeycloakLoginExpectingDenial,
  performKeycloakLoginForm,
  requireDotenvValue,
  withLdapAttributes,
  withLdapGroupMember,
} = require("./personas");
const { withBiberInGroup } = require("./_rbac");

test.use({ ignoreHTTPSErrors: true });

const env = {
  baseUrl: normalizeBaseUrl(process.env.CHECKMK_BASE_URL || "").replace(/\/$/, ""),
  guiUrl: normalizeBaseUrl(process.env.CHECKMK_GUI_URL || "").replace(/\/$/, ""),
  canonicalDomain: decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN),
  adminUsername: decodeDotenvQuotedValue(process.env.ADMIN_USERNAME),
  adminPassword: decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD),
  biberUsername: decodeDotenvQuotedValue(process.env.BIBER_USERNAME),
  biberPassword: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD),
  userGroupPath: decodeDotenvQuotedValue(process.env.RBAC_USER_GROUP_PATH),
  guestGroupPath: decodeDotenvQuotedValue(process.env.RBAC_GUEST_GROUP_PATH),
  biberDn: requireDotenvValue(process.env.BIBER_LDAP_DN, "BIBER_LDAP_DN"),
  userGroupDn: requireDotenvValue(process.env.LDAP_USER_GROUP_DN, "LDAP_USER_GROUP_DN"),
  guestGroupDn: requireDotenvValue(process.env.LDAP_GUEST_GROUP_DN, "LDAP_GUEST_GROUP_DN"),
  phoneAttribute: requireDotenvValue(process.env.LDAP_PHONE_ATTRIBUTE, "LDAP_PHONE_ATTRIBUTE"),
};

const ROLE_TIERS = [
  { groupPath: () => env.guestGroupPath, groupDn: () => env.guestGroupDn, alias: "Guest user" },
  { groupPath: () => env.userGroupPath, groupDn: () => env.userGroupDn, alias: "Normal monitoring user" },
];

/**
 * Sign in through the oauth2-proxy gate and wait for the Checkmk GUI.
 *
 * Args:
 *   page: the Playwright page to drive.
 *   username: the Keycloak login name.
 *   password: the Keycloak password.
 */
async function loginThroughGate(page, username, password) {
  await gotoOnion(page, `${env.baseUrl}/`, { waitUntil: "domcontentloaded" });
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "expected the gate to redirect to Keycloak" })
    .toContain("openid-connect/auth");
  await performKeycloakLoginForm(page, username, password);
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(90_000), message: `expected ${username} to reach the Checkmk GUI` })
    .toContain(env.canonicalDomain);
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "expected to leave the Checkmk login page" })
    .not.toContain("login.py");
  await expect(page.locator("body")).toContainText(/checkmk|dashboard|monitor|overview/i, {
    timeout: resolveTimeout(60_000),
  });
}

/**
 * Open the Setup user list as the administrator, waiting until the LDAP
 * sync has granted the administrator role that the page requires.
 *
 * Args:
 *   page: a Playwright page logged in as the administrator.
 */
async function openUserList(page) {
  await expect
    .poll(
      async () => {
        await gotoOnion(page, `${env.guiUrl}/wato.py?mode=users`, { waitUntil: "domcontentloaded" });
        return page.locator("table.data").count();
      },
      {
        timeout: resolveTimeout(180_000),
        intervals: [5_000, 10_000, 15_000],
        message: "the administrator group member MUST reach the Checkmk user management once the LDAP sync ran",
      },
    )
    .toBeGreaterThan(0);
}

/**
 * Start the LDAP user sync from the user list until the row of `username`
 * shows `expected`.
 *
 * Args:
 *   page: a Playwright page logged in as the administrator.
 *   username: the Checkmk user id whose row is inspected.
 *   expected: text the row must contain once the sync finished.
 */
async function syncUntilRowShows(page, username, expected) {
  await openUserList(page);
  await expect
    .poll(
      async () => {
        await gotoOnion(page, `${env.guiUrl}/wato.py?mode=users`, { waitUntil: "domcontentloaded" });
        const row = page.locator("table.data tr").filter({ hasText: new RegExp(`\\b${username}\\b`) }).first();
        const rowText = (await row.count()) ? await row.innerText() : "";
        if (rowText.includes(expected)) return rowText;
        const syncLink = page.locator("a:has-text('Synchronize users')").first();
        if (await syncLink.count()) {
          const syncResponse = page.waitForResponse((response) => response.url().includes("_sync=1"), {
            timeout: resolveTimeout(30_000),
          });
          await syncLink.evaluate((link) => link.click());
          await syncResponse.catch(() => {});
        }
        return rowText;
      },
      {
        timeout: resolveTimeout(180_000),
        intervals: [3_000, 5_000, 10_000],
        message: `the user list row of ${username} MUST show "${expected}" after the LDAP sync`,
      },
    )
    .toContain(expected);
}

/**
 * Run `fn` with a fresh page signed in as the platform administrator through
 * the Checkmk LDAP login form.
 *
 * Args:
 *   browser: the Playwright browser, used for an isolated context.
 *   fn: async body receiving the administrator page.
 */
async function withAdministrator(browser, fn) {
  const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const page = await ctx.newPage();
    await loginThroughForm(page, env.adminUsername, env.adminPassword);
    return await fn(page);
  } finally {
    await ctx.close().catch(() => {});
  }
}

/**
 * Submit the Checkmk login form with directory credentials.
 *
 * Args:
 *   page: the Playwright page to drive.
 *   username: the directory login name.
 *   password: the directory password.
 */
async function submitLoginForm(page, username, password) {
  await gotoOnion(page, `${env.guiUrl}/login.py`, { waitUntil: "domcontentloaded" });
  const userField = page.locator("input[name='_username']").first();
  await expect(userField).toBeVisible({ timeout: resolveTimeout(60_000) });
  await userField.fill(username);
  await page.locator("input[name='_password']").first().fill(password);
  await page.locator("input[name='_login'], button[name='_login']").first().click({ timeout: resolveTimeout(30_000) });
  await page.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(60_000) });
}

/**
 * Sign in through the Checkmk LDAP login form and wait for the Checkmk GUI.
 *
 * Args:
 *   page: the Playwright page to drive.
 *   username: the directory login name.
 *   password: the directory password.
 */
async function loginThroughForm(page, username, password) {
  await submitLoginForm(page, username, password);
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: `expected ${username} to leave the login page` })
    .not.toContain("login.py");
  await expect(page.locator("body")).toContainText(/checkmk|dashboard|monitor|overview/i, {
    timeout: resolveTimeout(60_000),
  });
}

test("biber: the LDAP login form refuses biber without a Checkmk role group", async ({ page }) => {
  skipUnlessServiceEnabled("ldap");
  skipUnlessServiceDisabled("sso");
  await submitLoginForm(page, env.biberUsername, env.biberPassword);
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(30_000) })
    .toContain("login.py");
  const cookies = await page.context().cookies(env.baseUrl);
  expect(
    cookies.some((cookie) => cookie.name.startsWith("auth_")),
    "the LDAP user filter MUST only find role group members, so biber gets no Checkmk session",
  ).toBe(false);
});

test("administrator: the LDAP login form admits the administrator group member", async ({ page }) => {
  skipUnlessServiceEnabled("ldap");
  skipUnlessServiceDisabled("sso");
  await submitLoginForm(page, env.adminUsername, env.adminPassword);
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "the administrator MUST leave the login page" })
    .not.toContain("login.py");
  await expect(page.locator("body")).toContainText(/checkmk|dashboard|monitor|overview/i, {
    timeout: resolveTimeout(60_000),
  });
});

test("rbac: biber without a Checkmk role group is refused by the oauth2-proxy gate", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(120_000)); // oauth2-proxy + Keycloak round-trip
  await page.context().clearCookies();
  await gotoOnion(page, `${env.baseUrl}/`, { waitUntil: "domcontentloaded" });
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "expected the gate to redirect to Keycloak" })
    .toContain("openid-connect/auth");
  await performKeycloakLoginExpectingDenial(page, env.biberUsername, env.biberPassword, env.canonicalDomain);
  const cookies = await page.context().cookies(env.baseUrl);
  expect(
    cookies.some((cookie) => cookie.name.startsWith("auth_")),
    "no Checkmk session may be minted for an account outside the Checkmk role groups",
  ).toBe(false);
});

test("administrator: the administrator group member holds the Checkmk Administrator role", async ({ browser }) => {
  skipUnlessServiceEnabled("ldap");
  skipUnlessServiceDisabled("sso");
  test.setTimeout(resolveTimeout(420_000)); // form login, up to three minutes for the first LDAP sync, then the sync polling
  await withAdministrator(browser, async (page) => {
    await syncUntilRowShows(page, env.adminUsername, "Administrator");
  });
});

for (const tier of ROLE_TIERS) {
  test(`biber: membership in the role group behind "${tier.alias}" admits biber through the oauth2-proxy gate`, async ({
    browser,
  }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(180_000)); // Keycloak group change around one oauth2-proxy + Keycloak round-trip
    await withBiberInGroup(browser, tier.groupPath(), async () => {
      const biberCtx = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        await loginThroughGate(await biberCtx.newPage(), env.biberUsername, env.biberPassword);
      } finally {
        await biberCtx.close().catch(() => {});
      }
    });
  });

  test(`biber: membership in the role group behind "${tier.alias}" admits biber with that Checkmk role`, async ({
    browser,
  }) => {
    skipUnlessServiceEnabled("ldap");
    skipUnlessServiceDisabled("sso");
    test.setTimeout(resolveTimeout(480_000)); // two form logins, the LDAP sync job and the user-list polling
    await withLdapGroupMember(tier.groupDn(), env.biberDn, async () => {
      const biberCtx = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        await loginThroughForm(await biberCtx.newPage(), env.biberUsername, env.biberPassword);
      } finally {
        await biberCtx.close().catch(() => {});
      }
      await withAdministrator(browser, async (page) => {
        await syncUntilRowShows(page, env.biberUsername, tier.alias);
      });
    });
  });
}

test("administrator: biber's directory phone number reaches the Checkmk pager address", async ({ browser }) => {
  skipUnlessServiceEnabled("ldap");
  skipUnlessServiceDisabled("sso");
  test.setTimeout(resolveTimeout(480_000)); // directory write, the LDAP sync job and the user-list polling
  const phone = `+49 30 ${Date.now() % 10_000_000}`;
  await withLdapAttributes(env.biberDn, { [env.phoneAttribute]: phone }, async () => {
    await withLdapGroupMember(env.guestGroupDn, env.biberDn, async () => {
      await withAdministrator(browser, async (page) => {
        await syncUntilRowShows(page, env.biberUsername, "Guest user");
        await expect
          .poll(
            async () => {
              await gotoOnion(page, `${env.guiUrl}/wato.py?mode=edit_user&edit=${encodeURIComponent(env.biberUsername)}`, {
                waitUntil: "domcontentloaded",
              });
              return page.locator("body").innerText();
            },
            {
              timeout: resolveTimeout(120_000),
              intervals: [5_000, 10_000],
              message: "the LDAP pager plug-in MUST copy the directory phone number into the Checkmk pager address",
            },
          )
          .toContain(phone);
      });
    });
  });
});
