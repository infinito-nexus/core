const { test, expect } = require("@playwright/test");
const { resolveTimeout, isOnionTarget } = require("./timeouts");
const { skipUnlessServiceDisabled, skipUnlessServiceEnabled } = require("./service-gating");
const { gotoOnion, normalizeBaseUrl, requireDotenvValue } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

function bbbBase() {
  return normalizeBaseUrl(requireDotenvValue(process.env.BBB_BASE_URL, "BBB_BASE_URL"));
}

function registrationEnabled() {
  return (
    requireDotenvValue(process.env.LOGIN_METHOD_REGISTRATION_ENABLED, "LOGIN_METHOD_REGISTRATION_ENABLED") === "true"
  );
}

async function openLanding(page) {
  await page.context().clearCookies();
  await gotoOnion(page, `${bbbBase()}/`, { waitUntil: "domcontentloaded" });
  const signIn = page.getByRole("button", { name: /sign\s*in/i }).or(page.getByRole("link", { name: /sign\s*in/i }));
  await expect(signIn.first(), "the Greenlight landing MUST offer a sign-in entry").toBeVisible({
    timeout: resolveTimeout(60_000),
  });
}

test("login methods: with sso on, the Greenlight landing offers the Keycloak sign-in only", async ({ page }) => {
  test.skip(isOnionTarget(), "BigBlueButton is WebRTC (UDP/ICE); not served over Tor");
  skipUnlessServiceEnabled("sso");
  await openLanding(page);
  await expect(page.locator("input[type='password']"), "no local password form may sit on the landing").toHaveCount(0);
  await expect(
    page.locator("a[href*='/signup']"),
    "under external authentication Greenlight MUST NOT offer its local Sign Up",
  ).toHaveCount(0);
});

test("login methods: with registration off, the Greenlight landing offers no Sign Up", async ({ page }) => {
  test.skip(isOnionTarget(), "BigBlueButton is WebRTC (UDP/ICE); not served over Tor");
  skipUnlessServiceDisabled("sso");
  test.skip(registrationEnabled(), "the inventory switches local self-registration on");
  await openLanding(page);
  await expect(
    page.locator("a[href*='/signup']"),
    "RegistrationMethod=invite MUST hide Greenlight's Sign Up from a visitor without an invitation",
  ).toHaveCount(0);
});
