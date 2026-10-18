const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { gotoOnion } = require("./personas");
const { baseUrl, loginAsAdministrator } = require("./jenkins-login");

test.use({ ignoreHTTPSErrors: true });

/**
 * Assert the global configuration carries a co-deployed partner's section.
 *
 * Args:
 *   page: the Playwright page to drive.
 *   service: the partner's service key, used in the failure message.
 *   section: a pattern the configuration body must match.
 */
async function expectPartnerSection(page, service, section) {
  await loginAsAdministrator(page);
  await gotoOnion(page, `${baseUrl}/manage/configure`, { waitUntil: "domcontentloaded" });

  const body = (await page.locator("body").innerText().catch(() => "")) || "";
  expect(
    body,
    `the global configuration must carry the ${service} section; it is absent when ` +
      "templates/plugins.txt.j2 did not emit the addon's plugin for this variant",
  ).toMatch(section);
}

test("partner gitea: the global configuration exposes the Gitea section", async ({ page }) => {
  skipUnlessServiceEnabled("gitea");
  test.setTimeout(resolveTimeout(180_000));
  await expectPartnerSection(page, "gitea", /gitea/i);
});

test("partner gitlab: the global configuration exposes the GitLab section", async ({ page }) => {
  skipUnlessServiceEnabled("gitlab");
  test.setTimeout(resolveTimeout(180_000));
  await expectPartnerSection(page, "gitlab", /gitlab/i);
});

test("partner mattermost: the global configuration exposes the Mattermost section", async ({ page }) => {
  skipUnlessServiceEnabled("mattermost");
  test.setTimeout(resolveTimeout(180_000));
  await expectPartnerSection(page, "mattermost", /mattermost/i);
});
