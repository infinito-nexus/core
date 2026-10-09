const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

test("addon email_channel: an Email::Account channel is provisioned against the partner mail server", async ({ page }) => {
  skipUnlessAddonEnabled("email_channel");
  skipUnlessServiceEnabled("email");
  test.setTimeout(resolveTimeout(180_000));

  const { zammadBaseUrl } = shared.env;
  expect(zammadBaseUrl, "ZAMMAD_BASE_URL must be set").toBeTruthy();

  await shared.signInAsApiBot(page);

  const response = await page.context().request.get(`${zammadBaseUrl}/api/v1/channels_email`, {
    headers: { Accept: "application/json" },
    failOnStatusCode: false,
    timeout: resolveTimeout(60_000),
  });

  expect(
    response.status(),
    `the admin email-channel API must answer for the Admin-role API bot; a 401/403 means the bot lost its role and a 404 means this Zammad has no channel admin surface (HTTP ${response.status()})`,
  ).toBe(200);

  const payload = await response.json();
  const channelIds = payload.channel_ids || [];
  expect(
    channelIds.length,
    "Zammad must carry at least one email channel; an empty list means files/ruby/apply/email_channel.rb never ran, so no mail is fetched or sent through the partner mail server",
  ).toBeGreaterThan(0);

  const channels = Object.values((payload.assets || {}).Channel || {});
  const emailAccounts = channels.filter((channel) => channel.area === "Email::Account");
  expect(
    emailAccounts.length,
    "the provisioned channel must be an Email::Account channel; another area means the bridge wired a different transport than the mail integration",
  ).toBeGreaterThan(0);

  const inboundAdapters = emailAccounts.map((channel) => ((channel.options || {}).inbound || {}).adapter);
  expect(
    inboundAdapters,
    "the email channel's inbound adapter must be imap, which is how the deployment fetches from the partner mail server",
  ).toContain("imap");

  const active = emailAccounts.some((channel) => channel.active === true);
  expect(
    active,
    "the Email::Account channel must be active; an inactive channel is provisioned but never polls, so inbound tickets never arrive",
  ).toBe(true);
});
