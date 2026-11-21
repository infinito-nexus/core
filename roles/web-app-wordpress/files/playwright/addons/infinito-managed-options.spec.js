const { test, expect } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { resolveTimeout } = require("../timeouts");
const { gotoOnion } = require("../personas");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

const PROBE_EMAIL = "managed-options-probe@example.invalid";
const MAIN_SITE_LINK = '#the-list tr:not(:has(input[name="allblogs[]"])) a.edit';
const SITE_SETTINGS_NONCE = 'form[action*="action=update-site"] input[name="_wpnonce"]';

/**
 * Args:
 *   page: Playwright page signed in as the administrator of the main site.
 * Returns:
 *   The admin email WordPress stores, as the General Settings page shows it on a single site and on a network alike.
 */
async function storedAdminEmail(page) {
  await gotoOnion(page, `${shared.env.wpBaseUrl}/wp-admin/options-general.php`, { waitUntil: "domcontentloaded" });
  return page.locator("#new_admin_email").inputValue();
}

/**
 * Args:
 *   page: Playwright page signed in as the administrator of a single site.
 *   managed: the admin email the deployment manages.
 */
async function writeOverRest(page, managed) {
  const nonce = await page.request.get(`${shared.env.wpBaseUrl}/wp-admin/admin-ajax.php?action=rest-nonce`);
  expect(nonce.ok(), "WordPress MUST hand the signed-in administrator a REST nonce").toBeTruthy();
  const headers = { "X-WP-Nonce": (await nonce.text()).trim() };
  const settings = `${shared.env.wpBaseUrl}/wp-json/wp/v2/settings`;

  const before = await page.request.get(settings, { headers });
  expect(before.ok(), "the administrator MUST read the site settings").toBeTruthy();
  expect((await before.json()).email, "the REST settings MUST serve the managed admin email").toBe(managed);

  const write = await page.request.post(settings, { headers, data: { email: PROBE_EMAIL } });
  expect(write.ok(), "the settings endpoint answers the write").toBeTruthy();
  expect((await write.json()).email, "the guard MUST keep the managed admin email against a REST write").toBe(managed);
}

/**
 * Args:
 *   page: Playwright page signed in as a super admin of the network.
 *   managed: the admin email the deployment manages.
 */
async function writeOnTheNetwork(page, managed) {
  await gotoOnion(page, `${shared.env.wpBaseUrl}/wp-admin/network/sites.php`, { waitUntil: "domcontentloaded" });
  const id = new URL(await page.locator(MAIN_SITE_LINK).first().getAttribute("href"), page.url()).searchParams.get("id");
  const screen = `${shared.env.wpBaseUrl}/wp-admin/network/site-settings.php?id=${id}`;

  await gotoOnion(page, screen, { waitUntil: "domcontentloaded" });
  expect(await page.locator("#admin_email").inputValue(), "the network MUST show the main site's managed admin email").toBe(managed);

  const write = await page.request.post(`${screen}&action=update-site`, {
    form: { _wpnonce: await page.locator(SITE_SETTINGS_NONCE).inputValue(), "option[admin_email]": PROBE_EMAIL },
  });
  expect(new URL(write.url()).searchParams.get("update"), "the network MUST accept the write of the main site's options").toBe(
    "updated",
  );
}

test("administrator: addon infinito-managed-options: a settings write keeps the managed admin email and the values file serves nothing", async ({ page }) => {
  skipUnlessAddonEnabled("infinito-managed-options");
  test.setTimeout(resolveTimeout(120_000));
  expect(shared.env.adminEmail, "ADMIN_EMAIL must be set").toBeTruthy();

  await shared.wpAdminLogin(page);
  const managed = await storedAdminEmail(page);
  expect(managed, "the site MUST carry the platform administrator's email as its managed admin email").toBe(shared.env.adminEmail);

  if (shared.env.multisiteEnabled) {
    await writeOnTheNetwork(page, managed);
  } else {
    await writeOverRest(page, managed);
  }
  expect(await storedAdminEmail(page), "the stored admin email MUST stay the managed one").toBe(managed);

  const file = await page.request.get(`${shared.env.wpBaseUrl}/wp-content/infinito-managed-options.php`);
  expect(await file.text(), "the managed values file MUST serve none of its values over HTTP").not.toContain(managed);
});
