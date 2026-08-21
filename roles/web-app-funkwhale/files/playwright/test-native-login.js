const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { decodeDotenvQuotedValue, isAuthChain, normalizeBaseUrl , gotoOnion } = require("./personas");
const { performKeycloakLoginForm } = require("./personas/utils/keycloak");

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");
const ldapEnabled = (process.env.LDAP_SERVICE_ENABLED || "").toLowerCase() === "true";
const ssoEnabled = (process.env.SSO_SERVICE_ENABLED || "").toLowerCase() === "true";

const PERSONAS = [
  {
    label: "biber",
    username: decodeDotenvQuotedValue(process.env.BIBER_USERNAME || ""),
    password: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD || ""),
  },
  {
    label: "administrator",
    username: decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || ""),
    password: decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || ""),
  },
];

const signInAffordance = (page) => page.getByText(/^\s*(log\s?in|sign\s?in)\s*$/i).first();

const hostOf = (page) => {
  try {
    return new URL(page.url()).hostname;
  } catch {
    return "";
  }
};
const onIdentityProvider = (page) => isAuthChain(page.url()) && hostOf(page) !== canonicalDomain;
const backOnApp = (page) => hostOf(page) === canonicalDomain && !isAuthChain(page.url());

for (const persona of PERSONAS) {
  test(`${persona.label}: native sign-in → authenticated surface → sign-out`, async ({ page }) => {
    test.skip(
      !ldapEnabled,
      "LDAP_SERVICE_ENABLED=false: tasks/main.yml provisions no local Funkwhale account, so no persona can sign in.",
    );
    test.setTimeout(resolveTimeout(180_000));

    expect(persona.username, `${persona.label} username must be set`).toBeTruthy();
    expect(persona.password, `${persona.label} password must be set`).toBeTruthy();

    await page.context().clearCookies();
    await gotoOnion(page, `${appBaseUrl}/login`, { waitUntil: "domcontentloaded" });

    if (ssoEnabled) {
      await expect
        .poll(() => onIdentityProvider(page), {
          timeout: resolveTimeout(60_000),
          message: "the oauth2 ACL protects /login, so the proxy must hand the persona to Keycloak",
        })
        .toBe(true);
      await performKeycloakLoginForm(page, persona.username, persona.password);
      await expect
        .poll(() => backOnApp(page), {
          timeout: resolveTimeout(60_000),
          message: `the oauth2 proxy gates /login, so Keycloak must hand back to ${canonicalDomain}`,
        })
        .toBe(true);
    }

    const password = page.locator("input[type='password']:visible").first();
    await expect(
      password,
      "Funkwhale serves its own sign-in form on /login; the proxy only gates the route, it does not create an application session",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    await page
      .locator(
        "input[autocomplete='username']:visible, input[type='text']:visible, input[type='email']:visible",
      )
      .first()
      .fill(persona.username);
    await password.fill(persona.password);
    await password.press("Enter");

    await expect(
      signInAffordance(page),
      `the sidebar must stop offering sign-in once ${persona.label} holds a Funkwhale session`,
    ).toBeHidden({ timeout: resolveTimeout(60_000) });

    await expect(page.locator("body")).toContainText(/library|playlist|artist|album|track|channel/i, {
      timeout: resolveTimeout(60_000),
    });

    const signOut = page
      .getByRole("link", { name: /log\s?out|sign\s?out/i })
      .or(page.getByRole("button", { name: /log\s?out|sign\s?out/i }))
      .first();
    const signOutReachable = await signOut
      .waitFor({ state: "visible", timeout: resolveTimeout(10_000) })
      .then(() => true)
      .catch(() => false);
    if (signOutReachable) {
      await signOut.click();
    } else {
      await gotoOnion(page, `${appBaseUrl}/logout`, { waitUntil: "domcontentloaded" });
    }

    const confirmSignOut = page.getByRole("button", { name: /(log|sign)\s?(me\s?)?out/i }).first();
    const confirmReachable = await confirmSignOut
      .waitFor({ state: "visible", timeout: resolveTimeout(10_000) })
      .then(() => true)
      .catch(() => false);
    if (confirmReachable) {
      await Promise.all([
        page
          .waitForResponse(
            (r) => r.url().includes("/api/v2/users/logout") && r.request().method() === "POST",
            { timeout: resolveTimeout(15_000) },
          )
          .catch(() => null),
        confirmSignOut.click(),
      ]);
    }

    await gotoOnion(page, appBaseUrl, { waitUntil: "domcontentloaded" });

    await expect(
      signInAffordance(page),
      `after sign-out Funkwhale must offer sign-in to ${persona.label} again`,
    ).toBeVisible({ timeout: resolveTimeout(60_000) });
  });
}
