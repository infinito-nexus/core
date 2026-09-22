const { test, expect } = require("@playwright/test");
const {
  normalizeBaseUrl,
  decodeDotenvQuotedValue,
  gotoOnion,
  performKeycloakLogin,
} = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const baseUrl = normalizeBaseUrl(process.env.OPENBAO_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");
const issuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");

const AUTH_PATH = "/ui/vault/auth?with=oidc";
const CALLBACK_PATH = "/ui/vault/auth/oidc/oidc/callback";

test.use({ ignoreHTTPSErrors: true });

test("oidc: the browser can reach the auth_url endpoint the login form depends on", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  await page.context().clearCookies();
  await gotoOnion(page, `${baseUrl}${AUTH_PATH}`, { waitUntil: "domcontentloaded" });

  const probe = await page.evaluate(async (callbackPath) => {
    try {
      const response = await fetch("/v1/auth/oidc/oidc/auth_url", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role: "", redirect_uri: `${window.location.origin}${callbackPath}` }),
      });
      const text = await response.text();
      return { ok: response.ok, status: response.status, body: text.slice(0, 400) };
    } catch (err) {
      return { ok: false, status: 0, body: `fetch threw: ${err && err.message}` };
    }
  }, CALLBACK_PATH);

  expect(
    probe.status,
    `auth_url request from the browser failed (status ${probe.status}): ${probe.body}`,
  ).toBe(200);
  expect(
    probe.body,
    "auth_url must carry a Keycloak authorization endpoint",
  ).toContain("openid-connect/auth");
});

test("oidc: the administrator signs in through Keycloak and lands in the OpenBao UI", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(240_000));
  await page.context().clearCookies();

  if (issuerUrl) {
    const warmup = await page.context().newPage();
    await gotoOnion(warmup, issuerUrl, { waitUntil: "domcontentloaded" }).catch(() => {});
    await warmup.close();
  }

  await gotoOnion(page, `${baseUrl}${AUTH_PATH}`, { waitUntil: "domcontentloaded" });

  const submit = page.getByRole("button", { name: /sign in with oidc provider/i }).first();
  await expect(submit, "the OIDC submit button must render").toBeVisible({
    timeout: resolveTimeout(60_000),
  });

  await expect
    .poll(
      async () =>
        page.evaluate(async (callbackPath) => {
          try {
            const response = await fetch("/v1/auth/oidc/oidc/auth_url", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                role: "",
                redirect_uri: `${window.location.origin}${callbackPath}`,
              }),
            });
            return response.status;
          } catch {
            return 0;
          }
        }, CALLBACK_PATH),
      {
        timeout: resolveTimeout(60_000),
        message: "the auth_url endpoint the OIDC form depends on never became reachable",
      },
    )
    .toBe(200);

  let popup = null;
  for (let attempt = 1; attempt <= 4 && !popup; attempt += 1) {
    const popupPromise = page
      .waitForEvent("popup", { timeout: resolveTimeout(15_000) })
      .catch(() => null);
    await submit.click({ timeout: resolveTimeout(15_000) });
    popup = await popupPromise;
  }
  expect(popup, "clicking the OIDC submit button must open the provider popup").toBeTruthy();

  await popup.waitForURL(/openid-connect\/auth/, { timeout: resolveTimeout(60_000) });
  expect(popup.url(), "the popup must reach the Keycloak authorization endpoint").toContain(
    "openid-connect/auth",
  );

  await performKeycloakLogin(popup, adminUsername, adminPassword, canonicalDomain);

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: "expected the parent page to leave the OpenBao auth surface after the OIDC exchange",
    })
    .not.toContain("/ui/vault/auth");
});
