const { expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const {
  decodeDotenvQuotedValue,
  gotoOnion,
  normalizeBaseUrl,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
} = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);

// Drive the Jitsi Meet pre-join chrome for an authenticated persona: navigate
// to a room URL and wait for the SPA's prejoin lobby to render. The spec MUST
// NOT actually start a media call (the headless Playwright runner has no
// camera permission) but reaching the prejoin lobby behind the oauth2-proxy
// gate proves the user is on the role's authenticated surface.
async function reachJitsiPrejoin(page, personaLabel, roomSuffix) {
  const roomName = `e2e-${personaLabel}-${roomSuffix}`.toLowerCase().replace(/[^a-z0-9-]/g, "");
  await gotoOnion(page, `${appBaseUrl}/${roomName}`, { waitUntil: "domcontentloaded" });
  const prejoin = page
    .getByRole("button", { name: /join meeting|join|beitreten/i })
    .or(page.locator('[data-testid="prejoin.joinMeeting"], #premeeting-screen'))
    .first();
  await expect(prejoin, `${personaLabel}: prejoin surface must render`).toBeVisible({
    timeout: resolveTimeout(60_000),
  });
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(30_000),
      message: `${personaLabel}: URL must include the room path`,
    })
    .toContain(`/${roomName}`);
}

// Open the prejoin "more options" / Settings panel so the admin scenario lands
// on a surface that biber does NOT exercise. Jitsi exposes a Settings link in
// the prejoin and in-meeting toolbar; presence of the panel satisfies the
// "admin authorisation: Settings link visible in the DOM" rule from the
// per-role playwright contract.
async function openJitsiSettingsPanel(page, personaLabel) {
  const settingsTrigger = page
    .getByRole("button", { name: /settings|einstellungen|more options|optionen/i })
    .or(page.locator('[aria-label*="settings" i], [aria-label*="einstellungen" i], [data-testid*="settings" i]'))
    .first();
  await expect(
    settingsTrigger,
    `${personaLabel}: a Settings / More-options control must be visible in the DOM`,
  ).toBeVisible({ timeout: resolveTimeout(30_000) });
}

async function beforeEach({ page }) {
  await page.setViewportSize({ width: 1440, height: 1100 });
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  await page.context().clearCookies();
}

module.exports = {
  env: {
    appBaseUrl,
    canonicalDomain,
  },
  reachJitsiPrejoin,
  openJitsiSettingsPanel,
  runGuestFlow,
  runBiberFlow,
  runAdminFlow,
  skipUnlessServiceEnabled,
  beforeEach,
};
