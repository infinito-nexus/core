const { test, expect } = require("@playwright/test");
const { resolveTimeout, isOnionTarget } = require("./timeouts");
const { decodeDotenvQuotedValue } = require("./personas");

// All Talk-admin assertion logic lives in this module so the gate flag,
// the env-presence guard, and the spreed-specific scraping helpers stay
// co-located with the single test that consumes them. Disabled when
// NEXTCLOUD_TALK_SETTINGS_CHECK_ENABLED is not "true" in the rendered
// `.env` (i.e. when the role's `services.talk.enabled` resolves false).
const nextcloudTalkSettingsCheckEnabled =
  decodeDotenvQuotedValue(process.env.NEXTCLOUD_TALK_SETTINGS_CHECK_ENABLED) === "true";
const nextcloudTalkSettingsUrl = decodeDotenvQuotedValue(process.env.NEXTCLOUD_TALK_SETTINGS_URL);
const nextcloudTalkExpectedSignalingUrl = decodeDotenvQuotedValue(process.env.NEXTCLOUD_TALK_EXPECTED_SIGNALING_URL);
const nextcloudTalkExpectedStunServer = decodeDotenvQuotedValue(process.env.NEXTCLOUD_TALK_EXPECTED_STUN_SERVER);
const nextcloudTalkExpectedTurnServer = decodeDotenvQuotedValue(process.env.NEXTCLOUD_TALK_EXPECTED_TURN_SERVER);
const nextcloudTalkUnexpectedStunServer = decodeDotenvQuotedValue(process.env.NEXTCLOUD_TALK_UNEXPECTED_STUN_SERVER);
const nextcloudTalkUnexpectedTurnServer = decodeDotenvQuotedValue(process.env.NEXTCLOUD_TALK_UNEXPECTED_TURN_SERVER);

// Error strings emitted by the spreed admin UI when a signaling / STUN / TURN
// test button reports a failure. Kept in one place so the list stays easy to
// audit against the spreed source.
const talkTestServerErrorPatterns = [
  /Error:\s*Cannot connect to server/i,
  /Error:\s*No working ICE candidates returned by the TURN server/i,
  /Error:\s*Server seems to be a Signaling server/i,
  /Testing server seems to be broken/i
];

// Positive success marker emitted by the spreed admin UI. Both the HPB
// signaling-server row (SignalingServer.vue) and the recording-backend row
// (RecordingServer.vue) render their reachability result inline via
// `<span class="test-connection">{{ connectionState }}</span>`, where
// connectionState becomes `"OK: Running version: <version>"` once the
// auto-mounted check (or our explicit Test-button click) succeeds.
//
// We require at least ONE successful row, not two: <RecordingServer> is
// `v-if="server && checked"` AND its parent <RecordingServers> only renders
// when `hasSignalingServers === true`, so the recording row can legitimately
// be absent on a stack that does not yet have an HPB signaling row stored
// (typical first-deploy ordering). Asserting two OK markers in that
// situation would false-fail on a healthy install.
const talkTestServerRequiredOkPattern = /OK:\s*Running version:\s*\S+/i;

// Talk admin settings are partly rendered as plain text and partly as
// `<input value="...">` fields. `innerText()` alone would miss the input
// values, so collect both text and form values before asserting presence or
// absence of configured / legacy endpoints.
async function collectNextcloudSettingsText(target) {
  const bodyText = await target.locator("body").innerText().catch(() => "");
  const formValues = await target.locator("input, textarea, select").evaluateAll((elements) => {
    return elements.flatMap((element) => {
      const values = [];
      const value = typeof element.value === "string" ? element.value.trim() : "";
      const text = typeof element.textContent === "string" ? element.textContent.trim() : "";

      if (value) {
        values.push(value);
      }

      if (text) {
        values.push(text);
      }

      return values;
    });
  }).catch(() => []);

  return [bodyText, ...formValues].filter(Boolean).join("\n");
}

async function expectNextcloudSettingValue(page, expectedValue, label) {
  await expect
    .poll(
      async () => collectNextcloudSettingsText(page),
      {
        timeout: resolveTimeout(30_000),
        message: `Expected ${label} to be visible in the Nextcloud Talk admin settings: ${expectedValue}`
      }
    )
    .toContain(expectedValue);
}

async function expectNextcloudSettingAbsent(page, unexpectedValue, label) {
  await expect
    .poll(
      async () => collectNextcloudSettingsText(page),
      {
        timeout: resolveTimeout(30_000),
        message: `Expected ${label} to stay absent in the Nextcloud Talk admin settings: ${unexpectedValue}`
      }
    )
    .not.toContain(unexpectedValue);
}

async function clickAllTalkTestServerButtonsAndVerify(page) {
  // Spreed renders the test result inside `<span class="test-connection">`
  // and the explicit re-test button (icon-only NcButton with
  // aria-label "Test this server") is `v-if="server && checked"` — i.e. it
  // only appears AFTER the auto-mount `checkServerVersion()` call returns,
  // and at that point the connectionState text is already in the span.
  // Wait for the result span to exist before measuring buttons so we do not
  // race the conditional render and silently click zero buttons.
  const connectionSpans = page.locator("span.test-connection");
  await connectionSpans
    .first()
    .waitFor({ state: "attached", timeout: resolveTimeout(60_000) })
    .catch(() => {
      // Continue — the assertion below will surface the real diagnostic.
    });

  // Re-trigger the check by clicking every Test button we can find. Spreed's
  // accessible name (English) is "Test this server" for both HPB signaling
  // and recording rows; older releases used "Test server", so match both.
  const testButtons = page.getByRole("button", { name: /^test( this)? server$/i });
  const total = await testButtons.count();
  for (let i = 0; i < total; i += 1) {
    const button = testButtons.nth(i);
    if (!(await button.isVisible().catch(() => false))) {
      continue;
    }
    await button.scrollIntoViewIfNeeded().catch(() => {});
    await button.click({ timeout: resolveTimeout(5_000) }).catch(() => {});
  }

  // Read the test-connection span texts directly instead of `document.body
  // .innerText`. innerText can omit content inside collapsed admin panels
  // and the explicit locator surfaces the exact element where spreed writes
  // the result, so failure messages name the actual rendered string.
  const readConnectionTexts = async () =>
    connectionSpans.allInnerTexts().catch(() => []);

  await expect
    .poll(readConnectionTexts, {
      timeout: resolveTimeout(60_000),
      message:
        "Expected at least one Talk admin row (.test-connection span) to render " +
        "'OK: Running version: <ver>' after the auto-check / Test-button click. " +
        "Empty array means the row was never rendered (HPB signaling server " +
        "config missing); a 'Status: Checking connection' value means the " +
        "auto-check is still pending; an 'Error:' value means HPB unreachable."
    })
    .toEqual(expect.arrayContaining([expect.stringMatching(talkTestServerRequiredOkPattern)]));

  // Iterate connection-span texts so the failure message points at the
  // exact row that broke instead of dumping the whole admin chrome.
  const texts = await readConnectionTexts();
  for (const text of texts) {
    for (const pattern of talkTestServerErrorPatterns) {
      expect(
        text,
        `Talk admin row reported a connection error matching ${pattern}: ${text}`
      ).not.toMatch(pattern);
    }
  }
}

exports.register = function (shared) {
  test("nextcloud talk admin settings", async ({ browser }) => {
    test.skip(!nextcloudTalkSettingsCheckEnabled, "Talk admin checks are disabled in the current Playwright env");
    test.skip(isOnionTarget(), "Nextcloud Talk realtime (HPB signaling + STUN/TURN) is WebRTC; not reachable over Tor");

    expect(nextcloudTalkSettingsUrl, "NEXTCLOUD_TALK_SETTINGS_URL must be set when Talk admin checks are enabled").toBeTruthy();
    expect(nextcloudTalkExpectedSignalingUrl, "NEXTCLOUD_TALK_EXPECTED_SIGNALING_URL must be set when Talk admin checks are enabled").toBeTruthy();
    expect(nextcloudTalkExpectedStunServer, "NEXTCLOUD_TALK_EXPECTED_STUN_SERVER must be set when Talk admin checks are enabled").toBeTruthy();
    expect(nextcloudTalkExpectedTurnServer, "NEXTCLOUD_TALK_EXPECTED_TURN_SERVER must be set when Talk admin checks are enabled").toBeTruthy();

    const browserContext = await browser.newContext({
      ignoreHTTPSErrors: true
    });

    try {
      const expectedTalkSettingsUrl = new URL(nextcloudTalkSettingsUrl);
      const adminPage = await browserContext.newPage();

      try {
        await shared.loginToStandaloneNextcloud(adminPage);
        await adminPage.goto(nextcloudTalkSettingsUrl, {
          waitUntil: "domcontentloaded",
          timeout: resolveTimeout(60_000)
        });
        await expect
          .poll(
            async () => {
              const currentUrl = new URL(adminPage.url());

              return {
                pathname: currentUrl.pathname,
                search: currentUrl.search
              };
            },
            {
              timeout: resolveTimeout(30_000),
              message: `Expected Nextcloud admin Talk settings page to load: ${nextcloudTalkSettingsUrl}`
            }
          )
          .toMatchObject({
            pathname: expectedTalkSettingsUrl.pathname,
            search: expectedTalkSettingsUrl.search
          });

        await shared.dismissBlockingNextcloudModals(adminPage, adminPage);
        await expectNextcloudSettingValue(adminPage, nextcloudTalkExpectedSignalingUrl, "Talk signaling URL");
        await expectNextcloudSettingValue(adminPage, nextcloudTalkExpectedStunServer, "Talk STUN server");
        await expectNextcloudSettingValue(adminPage, nextcloudTalkExpectedTurnServer, "Talk TURN server");

        if (nextcloudTalkUnexpectedStunServer) {
          await expectNextcloudSettingAbsent(adminPage, nextcloudTalkUnexpectedStunServer, "legacy Talk STUN server");
        }

        if (nextcloudTalkUnexpectedTurnServer) {
          await expectNextcloudSettingAbsent(adminPage, nextcloudTalkUnexpectedTurnServer, "legacy Talk TURN server");
        }

        await clickAllTalkTestServerButtonsAndVerify(adminPage);
      } finally {
        await adminPage.close().catch(() => {});
      }
    } finally {
      await browserContext.close().catch(() => {});
    }
  });
};
