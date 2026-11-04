const { test, expect } = require("@playwright/test");
const { resolveTimeout, isSplitRealmOidc } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { gotoOnion, keycloakAdminSetUserAttributes, normalizeUrl, readEnv, requireDotenvValue } = require("./personas");
const { signInViaOidc } = require("./mediawiki-session");

const env = {
  base: normalizeUrl(process.env.APP_BASE_URL),
  canonicalDomain: readEnv("CANONICAL_DOMAIN"),
  keycloakBaseUrl: normalizeUrl(process.env.KEYCLOAK_BASE_URL),
  realmName: readEnv("KEYCLOAK_REALM_NAME"),
  superAdminUsername: readEnv("SUPER_ADMIN_USERNAME"),
  superAdminPassword: readEnv("SUPER_ADMIN_PASSWORD"),
  biberUsername: readEnv("BIBER_USERNAME"),
  biberPassword: readEnv("BIBER_PASSWORD"),
};
const localeAttribute = requireDotenvValue(process.env.PROFILE_ATTRIBUTE_LOCALE, "PROFILE_ATTRIBUTE_LOCALE");
const zoneinfoAttribute = requireDotenvValue(process.env.PROFILE_ATTRIBUTE_ZONEINFO, "PROFILE_ATTRIBUTE_ZONEINFO");

const LOCALE = "de";
const ZONEINFO = "Europe/Berlin";

test.use({ ignoreHTTPSErrors: true });

test("biber: Keycloak locale and zoneinfo become the MediaWiki language and time zone preferences at OIDC login", async ({
  browser,
}) => {
  skipUnlessServiceEnabled("sso");
  test.skip(isSplitRealmOidc(), "clearnet app with an onion OIDC issuer: unreachable from one browser");
  test.setTimeout(resolveTimeout(240_000)); // one Keycloak attribute write and restore around one OIDC round-trip
  for (const [name, value] of Object.entries(env)) {
    expect(value, `${name} must be set`).toBeTruthy();
  }

  const api = await browser.newContext({ ignoreHTTPSErrors: true });
  const session = await browser.newContext({ ignoreHTTPSErrors: true });
  let previous = null;
  try {
    previous = await keycloakAdminSetUserAttributes(
      api.request,
      env.keycloakBaseUrl,
      env.realmName,
      env.biberUsername,
      { [localeAttribute]: LOCALE, [zoneinfoAttribute]: ZONEINFO },
      env.superAdminUsername,
      env.superAdminPassword,
    );

    const page = await session.newPage();
    await signInViaOidc(page, env.base, env.canonicalDomain, env.biberUsername, env.biberPassword);

    await gotoOnion(page, `${env.base}/index.php?title=Special:Preferences`, { waitUntil: "domcontentloaded" });
    await expect(
      page.locator("html"),
      `the ${localeAttribute} claim "${LOCALE}" MUST become biber's interface language`,
    ).toHaveAttribute("lang", LOCALE, { timeout: resolveTimeout(30_000) });
    await expect(
      page.locator("select[name='wplanguage']"),
      "Special:Preferences MUST lock the language preference that every OIDC login overwrites",
    ).toBeDisabled({ timeout: resolveTimeout(30_000) });
    await expect(
      page.locator("select[name='wptimecorrection']"),
      "Special:Preferences MUST lock the time zone preference that every OIDC login overwrites",
    ).toBeDisabled({ timeout: resolveTimeout(30_000) });

    const response = await gotoOnion(page, `${env.base}/api.php?action=query&meta=userinfo&uiprop=options&format=json`, {
      waitUntil: "domcontentloaded",
    });
    expect(response, "api.php MUST answer the userinfo query").toBeTruthy();
    const { options } = (await response.json()).query.userinfo;
    expect(options.language, `the ${localeAttribute} claim MUST set the language preference`).toBe(LOCALE);
    expect(
      options.timecorrection,
      `the ${zoneinfoAttribute} claim MUST set the time zone preference`,
    ).toMatch(new RegExp(`^ZoneInfo\\|-?\\d+\\|${ZONEINFO.replace("/", "\\/")}$`));
  } finally {
    if (previous) {
      await keycloakAdminSetUserAttributes(
        api.request,
        env.keycloakBaseUrl,
        env.realmName,
        env.biberUsername,
        previous,
        env.superAdminUsername,
        env.superAdminPassword,
      ).catch((error) => console.warn(`Restoring the profile attributes of ${env.biberUsername} failed: ${error}`));
    }
    await session.close().catch(() => {});
    await api.close().catch(() => {});
  }
});
