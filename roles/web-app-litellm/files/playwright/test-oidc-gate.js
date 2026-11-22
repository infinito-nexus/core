const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const {
  decodeDotenvQuotedValue,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  gotoOnion,
} = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.LITELLM_UI_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME || "");
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD || "");

test.use({ ignoreHTTPSErrors: true });

test("biber: the LiteLLM admin UI refuses a Keycloak account outside the administrator group", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(120_000));
  expect(baseUrl, "LITELLM_UI_BASE_URL must be set").toBeTruthy();
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();
  expect(biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();
  await page.context().clearCookies();

  const expectedBase = baseUrl.replace(/\/$/, "");
  await gotoOnion(page, `${expectedBase}/sso/key/generate`);
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `expected /sso/key/generate to redirect to ${oidcIssuerUrl}/protocol/openid-connect/auth`,
    })
    .toContain(`${oidcIssuerUrl}/protocol/openid-connect/auth`);

  await performKeycloakLoginForm(page, biberUsername, biberPassword);

  await expect(
    page.locator("body"),
    "the gateway MUST refuse biber at the SSO callback because biber is not in the administrator group",
  ).toContainText(/not in the restricted SSO group/i, { timeout: resolveTimeout(60_000) });
  const session = (await page.context().cookies()).find((c) => c.name === "token");
  expect(session, "a refused SSO login MUST NOT leave a LiteLLM UI session token").toBeUndefined();

  await gotoOnion(page, `${expectedBase}/ui`, { waitUntil: "domcontentloaded" });
  await expect
    .poll(() => new URL(page.url()).pathname.startsWith("/ui"), {
      timeout: resolveTimeout(30_000),
      message: "without a session the UI MUST hand biber back to the SSO login instead of keeping its own password form",
    })
    .toBe(false);
  await expect
    .poll(
      async () => {
        if (page.url().startsWith(oidcIssuerUrl) && (await page.locator("input[type=password]").count()) > 0) {
          return "keycloak form";
        }
        const text = await page.locator("body").innerText().catch(() => "");
        return /not in the restricted SSO group/i.test(text) ? "refused" : "pending";
      },
      {
        timeout: resolveTimeout(60_000),
        message: "the repeated SSO round-trip MUST end on the gateway's refusal or on the Keycloak sign-in form",
      },
    )
    .not.toBe("pending");
  const retry = (await page.context().cookies()).find((c) => c.name === "token");
  expect(retry, "the repeated SSO round-trip MUST NOT leave a LiteLLM UI session token either").toBeUndefined();
});
