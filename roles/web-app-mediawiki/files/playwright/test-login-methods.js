const { test, expect } = require("@playwright/test");
const { gotoOnion, normalizeBaseUrl, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const nativeOffered = process.env.LOGIN_METHOD_NATIVE_ENABLED === "true";
const registrationOffered = process.env.LOGIN_METHOD_REGISTRATION_ENABLED === "true";

async function openSpecialPage(page, title) {
  const base = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
  await page.context().clearCookies();
  await gotoOnion(page, `${base}/index.php?title=${title}`, { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) });
  await page.waitForLoadState("networkidle", { timeout: resolveTimeout(60_000) }).catch(() => {});
}

test("login methods: with SSO on the wiki shows the local password form only for the native method", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  await openSpecialPage(page, "Special:UserLogin");
  await expect(page.locator('input[name="wpPassword"]')).toHaveCount(nativeOffered ? 1 : 0);
});

test("login methods: with SSO on Special:CreateAccount offers local sign-up only for the registration method", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  await openSpecialPage(page, "Special:CreateAccount");
  await expect(page.locator("#wpCreateaccount")).toHaveCount(registrationOffered ? 1 : 0);
});
