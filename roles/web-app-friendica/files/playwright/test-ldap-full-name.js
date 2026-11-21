const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvQuotedValue, gotoOnion } = require("./personas");

const biberDirectoryFullName = decodeDotenvQuotedValue(process.env.BIBER_DIRECTORY_FULL_NAME || "");

exports.register = function (shared) {
  async function assertDirectoryFullName(browser, login) {
    expect(biberDirectoryFullName, "BIBER_DIRECTORY_FULL_NAME must be set").toBeTruthy();

    await shared.provisionBiberAccount(browser, login);

    const anonContext = await browser.newContext({ ignoreHTTPSErrors: true });
    try {
      const page = await anonContext.newPage();
      const profileUrl = `${shared.trimmedBaseUrl()}/profile/${shared.env.biberUsername}`;
      const response = await gotoOnion(page, profileUrl, { waitUntil: "domcontentloaded" });
      expect(response, `Expected a response for ${profileUrl}`).toBeTruthy();
      expect(response.status(), `Expected ${profileUrl} status < 400`).toBeLessThan(400);
      await expect(
        page.locator(".p-name, .fn").first(),
        "ldapauth MUST create the account with the full name attribute of the directory entry",
      ).toContainText(biberDirectoryFullName, { timeout: resolveTimeout(30_000) });
    } finally {
      await anonContext.close().catch(() => {});
    }
  }

  test("biber: ldapauth names the Friendica account with the directory full name", async ({ browser }) => {
    shared.skipUnlessServiceEnabled("ldap");
    await assertDirectoryFullName(browser, shared.loginViaFriendica);
  });
};
