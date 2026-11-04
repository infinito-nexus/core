const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { clickOidcLoginLink, gotoOnion, normalizeBaseUrl } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");

test("addon oidc: EspoCRM's sign-in hands over to the deployed Keycloak as its OIDC provider", async ({ page }) => {
  skipUnlessAddonEnabled("oidc");
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(180_000));

  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();

  const expectedBase = appBaseUrl.replace(/\/$/, "");
  await page.context().clearCookies();
  await gotoOnion(page, `${expectedBase}/`, { waitUntil: "domcontentloaded" });

  let authPage = page;
  if (!page.url().includes("openid-connect/auth")) {
    const strictLogin = page
      .getByRole("link", { name: /^\s*(log\s*in|sign\s*in|login|sso)\s*$/i })
      .or(page.getByRole("button", { name: /^\s*(log\s*in|sign\s*in|login|sso)\s*$/i }))
      .first();
    const looseLogin = page
      .getByRole("link", { name: /log\s*in|sign\s*in|sso/i })
      .or(page.getByRole("button", { name: /log\s*in|sign\s*in|sso/i }))
      .first();
    authPage = (await clickOidcLoginLink(page, strictLogin, looseLogin)) || page;
  }

  await expect
    .poll(() => authPage.url(), {
      timeout: resolveTimeout(60_000),
      message:
        "with authenticationMethod Oidc the sign-in must reach Keycloak's authorization " +
        "endpoint; a login form that stays on EspoCRM means ESPOCRM_CONFIG_OIDC_* never " +
        "reached the app's config and it still authenticates locally",
    })
    .toContain("openid-connect/auth");

  const authUrl = new URL(authPage.url());
  expect(
    authUrl.searchParams.get("client_id"),
    "the authorization request must carry the OIDC client id this deployment registered",
  ).toBeTruthy();
  expect(
    authUrl.searchParams.get("redirect_uri") || "",
    "the authorization request must come back to this EspoCRM instance, proving the callback " +
      "belongs to the deployed app and not to a default provider entry",
  ).toContain(new URL(expectedBase).host);
});
