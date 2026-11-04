const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvJsonList, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

const ADMIN_DASHBOARD_PATH = "/i/admin/dashboard";
const ADMIN_USERS_PATH = "/i/admin/users/list?limit=100";

async function readAdminFlags(page) {
  const rows = page.locator("tr.user-row");
  await expect(rows.first(), "expected the admin user list to show at least one account").toBeVisible({
    timeout: resolveTimeout(60_000),
  });
  const flags = [];
  for (const row of await rows.all()) {
    const username = await row.locator("input.action-check").getAttribute("data-username");
    const admin = (await row.locator(".badge-danger").filter({ hasText: /admin/i }).count()) > 0;
    flags.push({ username: String(username || "").toLowerCase(), admin });
  }
  return flags;
}

exports.register = function (shared) {
  const administrators = decodeDotenvJsonList(
    process.env.PIXELFED_RBAC_ADMINISTRATORS_JSON,
    "PIXELFED_RBAC_ADMINISTRATORS_JSON",
  );

  for (const { label, admitted } of [
    { label: "administrator", admitted: true },
    { label: "biber", admitted: false },
  ]) {
    const scenario = shared.loginScenarios.find((s) => s.label === label);

    test(`${label}: the administrator role group ${admitted ? "opens" : "keeps closed"} the Pixelfed admin dashboard`, async ({ page }) => {
      skipUnlessServiceEnabled("sso");
      if (label === "biber") {
        shared.skipWhenBiberMailboxFailsPixelfedValidation();
      }
      test.setTimeout(resolveTimeout(180_000));
      const base = shared.env.pixelfedBaseUrl.replace(/\/$/, "");

      await shared.loginToPixelfed(page, scenario);
      const response = await gotoOnion(page, `${base}${ADMIN_DASHBOARD_PATH}`, { waitUntil: "domcontentloaded" });
      expect(response, `expected an answer for ${ADMIN_DASHBOARD_PATH}`).toBeTruthy();
      expect(response.status(), `expected ${ADMIN_DASHBOARD_PATH} to answer without a server error`).toBeLessThan(400);
      if (admitted) {
        expect(page.url(), `expected ${scenario.username} to stay on the admin dashboard`).toContain(ADMIN_DASHBOARD_PATH);
      } else {
        expect(page.url(), `expected ${scenario.username} to be sent away from the admin dashboard`).not.toContain("/i/admin");
      }

      await gotoOnion(page, `${base}/`, { waitUntil: "domcontentloaded" });
      await shared.logoutFromPixelfed(page, scenario);
    });
  }

  test("administrator: every Pixelfed admin flag belongs to a member of the administrator role group", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(180_000));
    const scenario = shared.loginScenarios.find((s) => s.label === "administrator");
    const biber = shared.loginScenarios.find((s) => s.label === "biber");
    const base = shared.env.pixelfedBaseUrl.replace(/\/$/, "");
    expect(administrators, "expected the administrator role group to list at least the administrator").toContain(
      scenario.username.toLowerCase(),
    );

    await shared.loginToPixelfed(page, scenario);
    await gotoOnion(page, `${base}${ADMIN_USERS_PATH}`, { waitUntil: "domcontentloaded" });
    const flags = await readAdminFlags(page);
    expect(
      flags.some((flag) => flag.username === scenario.username.toLowerCase() && flag.admin),
      `expected ${scenario.username} to carry the Pixelfed admin flag`,
    ).toBe(true);
    for (const flag of flags.filter((entry) => entry.admin)) {
      expect(administrators, `expected admin ${flag.username} to be a member of the administrator role group`).toContain(flag.username);
    }
    expect(
      flags.filter((flag) => flag.admin).map((flag) => flag.username),
      "expected biber, who holds no role group, to carry no Pixelfed admin flag",
    ).not.toContain(biber.username.toLowerCase());

    await gotoOnion(page, `${base}/`, { waitUntil: "domcontentloaded" });
    await shared.logoutFromPixelfed(page, scenario);
  });
};
