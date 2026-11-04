const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");
const {
  confirmKeycloakLogoutIfPrompted,
  decodeDotenvQuotedValue,
  gotoOnion,
  installCspViolationObserver,
  normalizeBaseUrl,
} = require("./personas");
const { signInViaKeycloak } = require("./joomla-session");

const base = normalizeBaseUrl(process.env.JOOMLA_BASE_URL);
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);

test.use({ ignoreHTTPSErrors: true });

test("biber: the com_users Log out button ends the Keycloak session", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(180_000)); // two OIDC round-trips around one Keycloak end-session confirmation
  expect(base, "JOOMLA_BASE_URL must be set").toBeTruthy();
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set when OIDC is enabled").toBeTruthy();

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const page = await context.newPage();
    await installCspViolationObserver(page);
    await signInViaKeycloak(page, base, biberUsername, biberPassword);

    await gotoOnion(page, `${base}/index.php?option=com_users&view=login`);
    const logout = page.locator("main .com-users-logout").getByRole("button", { name: /log\s*out/i });
    await expect(logout, "com_users must render its Log out button for a signed-in account").toBeVisible({
      timeout: resolveTimeout(30_000),
    });
    await logout.click({ timeout: resolveTimeout(30_000) });

    if (!isServiceEnabled("logout")) {
      await expect
        .poll(() => page.url(), {
          timeout: resolveTimeout(60_000),
          message: "plg_system_keycloak must send the Log out click to the issuer's end-session endpoint",
        })
        .toContain(`${oidcIssuerUrl}/protocol/openid-connect/logout`);
    }
    await page.waitForLoadState("networkidle", { timeout: resolveTimeout(30_000) }).catch(() => {});
    await confirmKeycloakLogoutIfPrompted(page);

    await gotoOnion(page, `${base}/`);
    await expect
      .poll(() => page.url(), {
        timeout: resolveTimeout(60_000),
        message: "after the Log out click Joomla must treat biber as a guest again",
      })
      .toContain(`${oidcIssuerUrl}/protocol/openid-connect/auth`);
    await expect(
      page.locator("input[name='username'], input#username").first(),
      "Keycloak must ask for credentials again, which it does only once the end-session request closed its SSO session",
    ).toBeVisible({ timeout: resolveTimeout(30_000) });
  } finally {
    await context.close().catch(() => {});
  }
});
