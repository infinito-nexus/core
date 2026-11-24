const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");
const { gotoOnion } = require("../personas");

const AUTHORIZE_PATH = /\/oauth\/authorize/i;
const SENSITIVE_CONFIG_PATH = /\/apps\/integration_zammad\/sensitive-config(\?|$)/i;

/**
 * Args:
 *   page: the personal connected-accounts page.
 *   connect: the visible personal "Connect to Zammad" control.
 *
 * Returns:
 *   The URL of the partner /oauth/authorize request the connect issued: the control's own href when it links there,
 *   else the request its click sends after the app stored the OAuth state through PUT sensitive-config.
 */
async function connectToZammad(page, connect) {
  const href = await connect.getAttribute("href");
  if (href && AUTHORIZE_PATH.test(href)) return href;

  const stateSaved = page
    .waitForResponse(
      (response) => response.request().method() === "PUT" && SENSITIVE_CONFIG_PATH.test(response.url()),
      { timeout: resolveTimeout(30_000) }
    )
    .catch(() => null);
  const authorizeRequest = page
    .waitForRequest((request) => AUTHORIZE_PATH.test(request.url()), { timeout: resolveTimeout(30_000) })
    .catch(() => null);

  await shared.clickWithModalRetry(page, page, connect);

  const saved = await stateSaved;
  expect(
    saved,
    "the Connect to Zammad click must PUT the OAuth state to /apps/integration_zammad/sensitive-config"
  ).toBeTruthy();
  expect(
    saved.ok(),
    "integration_zammad must accept the OAuth state PUT to /apps/integration_zammad/sensitive-config"
  ).toBe(true);
  const request = await authorizeRequest;
  expect(
    request,
    "after the OAuth state was stored, the Connect to Zammad click must send the browser to the partner /oauth/authorize"
  ).toBeTruthy();
  return request.url();
}

test("integration integration_zammad: per-user OAuth connect reaches the partner Zammad authorize endpoint", async ({ browser }) => {
  skipUnlessAddonEnabled("integration_zammad");
  test.setTimeout(resolveTimeout(120_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    await gotoOnion(page,
      new URL("settings/admin/connected-accounts", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) }
    );
    await shared.dismissBlockingNextcloudModals(page, page);

    const zammadPrefs = page.locator("#zammad_prefs");
    await expect(
      zammadPrefs.first(),
      "the Zammad integration admin section (#zammad_prefs) must render when integration_zammad is enabled"
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    const instanceInput = zammadPrefs
      .getByRole("textbox", { name: /zammad instance address/i })
      .or(zammadPrefs.locator('input[type="text"], input[type="url"]'));
    await expect(
      instanceInput.first(),
      "the Zammad instance-address field must be present in the admin section"
    ).toBeVisible({ timeout: resolveTimeout(30_000) });

    const instanceUrl = ((await instanceInput.first().inputValue()) || "").trim();
    expect(
      /^https?:\/\//i.test(instanceUrl),
      "oauth_instance_url must be a real partner URL (the addon hook pins it to the partner Zammad base URL)"
    ).toBeTruthy();

    const nextcloudHost = new URL(shared.env.nextcloudBaseUrl).host;
    const partnerHost = new URL(instanceUrl).host;
    expect(
      partnerHost,
      "the Zammad instance URL must not point back at Nextcloud itself"
    ).not.toBe(nextcloudHost);

    await gotoOnion(page,
      new URL("settings/user/connected-accounts", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) }
    );
    await shared.dismissBlockingNextcloudModals(page, page);

    const connect = page
      .locator('a[href*="/oauth/authorize"]')
      .or(page.getByRole("button", { name: /connect to zammad/i }))
      .or(page.getByRole("link", { name: /connect to zammad/i }))
      .first();
    await expect(
      connect,
      "the personal 'Connect to Zammad' control must render once the partner OAuth client is provisioned; its absence means the coupling failed to land"
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    const authorize = new URL(await connectToZammad(page, connect), instanceUrl);
    expect(
      authorize.host,
      "the Zammad OAuth authorize must be served by the partner instance, not Nextcloud"
    ).not.toBe(nextcloudHost);
    expect(
      authorize.host,
      "the OAuth authorize host must match the configured partner instance URL"
    ).toBe(partnerHost);
    expect(
      authorize.pathname,
      "the per-user connect must initiate OAuth on the partner /oauth/authorize endpoint"
    ).toContain("/oauth/authorize");
    const clientId = authorize.searchParams.get("client_id") || "";
    expect(
      clientId.length,
      "the authorize request must carry the provisioned OAuth client_id (proves the partner-registered app)"
    ).toBeGreaterThan(0);
    expect(
      clientId.includes("|"),
      "the client_id must be the plaintext OAuth uid, not an ICrypto ciphertext - a '|' means integration_zammad read an encrypted value it could not decrypt (NC_ENC_MODE/encryption regression)"
    ).toBe(false);
    expect(
      authorize.searchParams.get("response_type"),
      "the coupling must use the authorization-code grant"
    ).toBe("code");
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
