const { test, expect } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { resolveTimeout } = require("../timeouts");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

const PROBE_EMAIL = "managed-options-probe@example.invalid";

test("administrator: addon infinito-managed-options: a REST write keeps the managed admin email and the values file serves nothing", async ({ page }) => {
  skipUnlessAddonEnabled("infinito-managed-options");
  test.setTimeout(resolveTimeout(120_000));

  await shared.wpAdminLogin(page);
  const nonce = await page.request.get(`${shared.env.wpBaseUrl}/wp-admin/admin-ajax.php?action=rest-nonce`);
  expect(nonce.ok(), "WordPress MUST hand the signed-in administrator a REST nonce").toBeTruthy();
  const headers = { "X-WP-Nonce": (await nonce.text()).trim() };
  const settings = `${shared.env.wpBaseUrl}/wp-json/wp/v2/settings`;

  const before = await page.request.get(settings, { headers });
  expect(before.ok(), "the administrator MUST read the site settings").toBeTruthy();
  const managed = (await before.json()).email;
  expect(managed, "the site MUST carry a managed admin email").toBeTruthy();

  const write = await page.request.post(settings, { headers, data: { email: PROBE_EMAIL } });
  expect(write.ok(), "the settings endpoint answers the write").toBeTruthy();
  expect((await write.json()).email, "the guard MUST keep the managed admin email against a REST write").toBe(managed);

  const after = await page.request.get(settings, { headers });
  expect((await after.json()).email, "the stored admin email MUST stay the managed one").toBe(managed);

  const file = await page.request.get(`${shared.env.wpBaseUrl}/wp-content/infinito-managed-options.php`);
  expect(await file.text(), "the managed values file MUST serve none of its values over HTTP").not.toContain(managed);
});
