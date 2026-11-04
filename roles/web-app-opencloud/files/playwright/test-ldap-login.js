const { test, expect } = require("./onion-test");
const { resolveTimeout } = require("./timeouts");

const { gotoOnion } = require("./personas");
const { skipUnlessServiceDisabled, skipUnlessServiceEnabled } = require("./service-gating");
const {
  adminPassword,
  adminUsername,
  baseUrl,
  biberPassword,
  biberUsername,
  logoutThroughAccountMenu,
} = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

const base = baseUrl.replace(/\/$/, "");

const PERSONAS = [
  { label: "administrator", username: adminUsername, password: adminPassword },
  { label: "biber", username: biberUsername, password: biberPassword },
];

async function allowBrowser(page) {
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem(
        "forceAllowOldBrowser",
        JSON.stringify({ expiry: Date.now() + 30 * 24 * 60 * 60 * 1000 }),
      );
    } catch {}
  });
}

async function signedInAccount(page) {
  const result = await page.evaluate(async () => {
    let token = "";
    for (const store of [window.sessionStorage, window.localStorage]) {
      for (let index = 0; index < store.length; index += 1) {
        try {
          const value = JSON.parse(store.getItem(store.key(index)) || "null");
          if (value && typeof value.access_token === "string") {
            token = value.access_token;
          }
        } catch {}
      }
    }
    if (!token) {
      return { error: "no access token in the browser storage" };
    }
    const me = await fetch("/graph/v1.0/me", { headers: { Authorization: `Bearer ${token}` } });
    if (!me.ok) {
      return { error: `GET /graph/v1.0/me answered ${me.status}` };
    }
    return { account: await me.json() };
  });
  expect(result.error, `the OpenCloud account probe failed: ${result.error}`).toBeUndefined();
  return result.account;
}

for (const persona of PERSONAS) {
  test(`${persona.label}: built-in sign-in binds against the directory → files view → sign-out`, async ({ page }) => {
    skipUnlessServiceEnabled("ldap");
    skipUnlessServiceDisabled("sso");
    expect(persona.username, `${persona.label} username must be set`).toBeTruthy();
    expect(persona.password, `${persona.label} password must be set`).toBeTruthy();

    await allowBrowser(page);
    await gotoOnion(page, `${base}/`);

    const usernameField = page.locator("#oc-login-username");
    await expect(
      usernameField,
      "without sso the SPA must hand the visitor to the sign-in form of the built-in identity provider",
    ).toBeVisible({ timeout: resolveTimeout(90_000) });
    await usernameField.fill(persona.username);
    await page.locator("#oc-login-password").fill(persona.password);
    await page.locator("#oc-login-password").press("Enter");

    await expect(
      page.locator("#oc-topbar"),
      `the built-in identity provider must accept the directory credentials of ${persona.label}`,
    ).toBeVisible({ timeout: resolveTimeout(90_000) });
    await expect(page.getByRole("link", { name: /personal files/i })).toBeVisible({ timeout: resolveTimeout(30_000) });

    const account = await signedInAccount(page);
    expect(
      account.onPremisesSamAccountName,
      `the session must belong to the directory account of ${persona.label}, resolved through OC_LDAP_USER_SCHEMA_USERNAME`,
    ).toBe(persona.username);
    expect(account.displayName, "OpenCloud must read the display name from OC_LDAP_USER_SCHEMA_DISPLAYNAME").toBeTruthy();

    await logoutThroughAccountMenu(page);

    await gotoOnion(page, `${base}/`);
    await expect(
      page.locator("#oc-login-username"),
      `after sign-out a protected request must send ${persona.label} back to the sign-in form`,
    ).toBeVisible({ timeout: resolveTimeout(90_000) });
  });
}
