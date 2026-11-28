const { test, expect } = require("./onion-test");
const { resolveTimeout } = require("./timeouts");

const { gotoOnion, requireDotenvValue, withLdapAttributes } = require("./personas");
const { skipUnlessServiceDisabled, skipUnlessServiceEnabled } = require("./service-gating");
const { baseUrl, biberUsername, biberPassword, logoutThroughAccountMenu, ssoLoginAndAssertUsername } = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

const directory = {
  biberDn: requireDotenvValue(process.env.BIBER_LDAP_DN, "BIBER_LDAP_DN"),
  displayNameAttribute: requireDotenvValue(process.env.LDAP_DISPLAY_NAME_ATTRIBUTE, "LDAP_DISPLAY_NAME_ATTRIBUTE"),
};

async function readAccountMenuDisplayName(page) {
  await page.locator("#_userMenuButton").click({ timeout: resolveTimeout(30_000) });
  const accountMenu = page.locator("#account-info-container");
  await expect(accountMenu, "the account menu must open from the top bar").toBeVisible({ timeout: resolveTimeout(30_000) });
  return accountMenu.locator("span > span.block").first();
}

async function signInThroughBuiltInIdentityProvider(page, username, password) {
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem(
        "forceAllowOldBrowser",
        JSON.stringify({ expiry: Date.now() + 30 * 24 * 60 * 60 * 1000 }),
      );
    } catch {}
  });
  await gotoOnion(page, `${baseUrl.replace(/\/$/, "")}/`);
  const usernameField = page.locator("#oc-login-username");
  await expect(
    usernameField,
    "without sso the SPA must hand the visitor to the sign-in form of the built-in identity provider",
  ).toBeVisible({ timeout: resolveTimeout(90_000) });
  await usernameField.fill(username);
  await page.locator("#oc-login-password").fill(password);
  await page.locator("#oc-login-password").press("Enter");
  await expect(page.locator("#oc-topbar"), "the built-in identity provider must accept biber's directory credentials").toBeVisible({
    timeout: resolveTimeout(90_000),
  });
}

test("biber: opencloud account menu shows the display name after the SSO sign-in", async ({ page }) => {
  skipUnlessServiceEnabled("sso");

  await ssoLoginAndAssertUsername(page, biberUsername, biberPassword);

  const displayName = await readAccountMenuDisplayName(page);
  await expect
    .poll(async () => ((await displayName.textContent()) || "").trim(), {
      timeout: resolveTimeout(30_000),
      message: "the account menu must show the display name of the signed-in account",
    })
    .not.toBe("");
  await page.locator("#_userMenuButton").click({ timeout: resolveTimeout(30_000) });

  await logoutThroughAccountMenu(page);
});

test("biber: opencloud account menu shows the display name written to the directory", async ({ page }) => {
  skipUnlessServiceEnabled("ldap");
  skipUnlessServiceDisabled("sso");
  test.setTimeout(resolveTimeout(180_000)); // directory write and restore around one built-in identity provider sign-in

  const expected = `Biber Directory ${Date.now()}`;
  await withLdapAttributes(directory.biberDn, { [directory.displayNameAttribute]: expected }, async () => {
    await signInThroughBuiltInIdentityProvider(page, biberUsername, biberPassword);

    const displayName = await readAccountMenuDisplayName(page);
    await expect
      .poll(async () => ((await displayName.textContent()) || "").trim(), {
        timeout: resolveTimeout(30_000),
        message: `OpenCloud must read the display name from the directory attribute ${directory.displayNameAttribute} (OC_LDAP_USER_SCHEMA_DISPLAYNAME)`,
      })
      .toBe(expected);
    await page.locator("#_userMenuButton").click({ timeout: resolveTimeout(30_000) });

    await logoutThroughAccountMenu(page);
  });
});
