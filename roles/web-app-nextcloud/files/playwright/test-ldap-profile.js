const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvQuotedValue, requireDotenvValue, withLdapAttributes } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

const DIRECTORY_MANAGED_FIELDS = ["phone", "website", "address", "organisation", "role", "biography"];

const env = {
  biberDn: decodeDotenvQuotedValue(process.env.BIBER_LDAP_DN),
  phoneAttribute: requireDotenvValue(process.env.LDAP_PHONE_ATTRIBUTE, "LDAP_PHONE_ATTRIBUTE"),
  ldapCacheTtlSeconds: Number(decodeDotenvQuotedValue(process.env.NEXTCLOUD_LDAP_CACHE_TTL)),
};

exports.register = function (shared) {
  test("biber: nextcloud profile fields synced from the directory are read-only", async ({ browser }) => {
    skipUnlessServiceEnabled("ldap");
    const biberContext = await browser.newContext({ ignoreHTTPSErrors: true });
    const biberPage = await biberContext.newPage();
    try {
      await shared.loginToStandaloneNextcloud(biberPage, shared.env.biberUsername, shared.env.biberPassword);
      const response = await biberPage.request.get(
        new URL("ocs/v2.php/cloud/user/fields?format=json", shared.env.nextcloudBaseUrl).toString(),
        { headers: { "OCS-APIRequest": "true", Accept: "application/json" }, timeout: resolveTimeout(30_000) },
      );
      const body = await response.text();
      expect(response.ok(), `the editable-fields endpoint must answer for biber, got ${response.status()}: ${body.slice(0, 300)}`).toBe(true);
      const editable = JSON.parse(body).ocs.data;
      expect(editable, "the editable-fields endpoint must list the fields Nextcloud still manages itself").toContain("headline");
      for (const field of DIRECTORY_MANAGED_FIELDS) {
        expect(editable, `the ${field} field is synced from the directory and must not be editable in Nextcloud`).not.toContain(field);
      }

      await biberPage.goto(new URL("settings/user", shared.env.nextcloudBaseUrl).toString(), {
        waitUntil: "domcontentloaded",
        timeout: resolveTimeout(60_000),
      });
      await shared.waitForVisibleCandidate(
        biberPage,
        shared.getNextcloudShellCandidates(biberPage),
        resolveTimeout(60_000),
        "Timed out waiting for biber's personal settings in the Nextcloud shell",
      );
      await shared.logoutStandaloneNextcloud(biberPage);
    } finally {
      await biberContext.close().catch(() => {});
    }
  });

  test("biber: a phone number changed in the directory reaches Nextcloud on the next directory password login", async ({ request }) => {
    skipUnlessServiceEnabled("ldap");
    expect(env.ldapCacheTtlSeconds, "NEXTCLOUD_LDAP_CACHE_TTL must be a number of seconds").toBeGreaterThan(0);
    const refreshBudgetMs = (env.ldapCacheTtlSeconds + 90) * 1000;
    test.setTimeout(refreshBudgetMs + resolveTimeout(120_000)); // the LDAP cache TTL of user_ldap plus one directory attribute write and restore

    const phone = `+49301${String(Date.now()).slice(-6)}`;
    const basic = Buffer.from(`${shared.env.biberUsername}:${shared.env.biberPassword}`).toString("base64");
    await withLdapAttributes(env.biberDn, { [env.phoneAttribute]: phone }, async () => {
      await expect
        .poll(
          async () => {
            const response = await request.get(new URL("ocs/v2.php/cloud/user?format=json", shared.env.nextcloudBaseUrl).toString(), {
              headers: { "OCS-APIRequest": "true", Accept: "application/json", Authorization: `Basic ${basic}` },
              timeout: resolveTimeout(30_000),
            });
            if (!response.ok()) {
              return `HTTP ${response.status()}`;
            }
            return (await response.json()).ocs.data.phone;
          },
          {
            timeout: refreshBudgetMs,
            intervals: [5_000],
            message: `a password login of biber against the directory must copy the changed ${env.phoneAttribute} onto the Nextcloud profile`,
          },
        )
        .toBe(phone);
    });
  });
};
