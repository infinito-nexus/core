const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceDisabled, skipUnlessServiceEnabled } = require("../service-gating");
const shared = require("../_shared");
const { apiFetchOnion, decodeDotenvQuotedValue } = require("../personas");

const CLIENT = 'MediaBrowser Client="playwright", Device="spec", DeviceId="infinito-spec", Version="1.0.0"';

test.use({ ignoreHTTPSErrors: true });

test.beforeEach(shared.beforeEach);

test("biber: signs in via the ldap-authentication addon and lands on the Jellyfin home", async ({ page }) => {
  skipUnlessAddonEnabled("ldap-authentication");
  skipUnlessServiceEnabled("ldap");
  skipUnlessServiceDisabled("sso");
  test.setTimeout(resolveTimeout(60_000));
  expect(shared.env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
  expect(shared.env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();

  await shared.signInViaLdap(page, shared.env.biberUsername, shared.env.biberPassword, "biber-ldap");
  await expect(page.locator("body")).toContainText(/home|library|media|jellyfin/i, { timeout: resolveTimeout(60_000) });
  const user = await shared.sessionUser(page, "biber-ldap");
  expect(user.Name, "the Jellyfin account the LDAP plugin signs biber into must carry the directory login attribute").toBe(shared.env.biberUsername);
  await shared.logout(page, "biber-ldap");
});

test("addon ldap-authentication: the LDAP plugin reads passwords from the directory password attribute", async ({ page }) => {
  skipUnlessAddonEnabled("ldap-authentication");
  skipUnlessServiceEnabled("ldap");
  test.setTimeout(resolveTimeout(60_000));
  const passwordAttribute = decodeDotenvQuotedValue(process.env.LDAP_PASSWORD_ATTRIBUTE);
  expect(passwordAttribute, "LDAP_PASSWORD_ATTRIBUTE must be set").toBeTruthy();

  const login = await apiFetchOnion(page.request, `${shared.env.jellyfinBaseUrl}/Users/AuthenticateByName`, {
    method: "POST",
    headers: { "X-Emby-Authorization": CLIENT },
    data: { Username: shared.env.adminUsername, Pw: shared.env.adminNativePassword },
  });
  expect(login.status(), "the administrator must authenticate against the Jellyfin API").toBe(200);
  const headers = { "X-Emby-Token": (await login.json()).AccessToken };

  const plugins = await apiFetchOnion(page.request, `${shared.env.jellyfinBaseUrl}/Plugins`, { method: "GET", headers });
  expect(plugins.status(), "GET /Plugins must answer for the administrator").toBe(200);
  const ldapPlugin = (await plugins.json()).find((plugin) => /ldap/i.test(plugin.Name));
  expect(ldapPlugin, "the LDAP Authentication plugin must be installed").toBeTruthy();

  const configuration = await apiFetchOnion(page.request, `${shared.env.jellyfinBaseUrl}/Plugins/${ldapPlugin.Id}/Configuration`, {
    method: "GET",
    headers,
  });
  expect(configuration.status(), "GET /Plugins/{id}/Configuration must answer for the administrator").toBe(200);
  expect((await configuration.json()).LdapPasswordAttribute, "LdapPasswordAttribute must name the directory password attribute").toBe(passwordAttribute);
});
