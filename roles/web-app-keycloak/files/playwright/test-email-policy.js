const { test, expect } = require("@playwright/test");
const { isSplitRealmOidc, resolveTimeout } = require("./timeouts");
const {
  gotoOnion,
  keycloakAdminToken,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  requireDotenvValue,
  waitForEmailInMailbox,
  webmailSsoLogin,
} = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

const appBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const issuerBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.ISSUER_BASE_URL, "ISSUER_BASE_URL"));
const realmName = requireDotenvValue(process.env.KEYCLOAK_REALM_NAME, "KEYCLOAK_REALM_NAME");
const biberUsername = requireDotenvValue(process.env.BIBER_USERNAME, "BIBER_USERNAME");
const biberPassword = requireDotenvValue(process.env.BIBER_PASSWORD, "BIBER_PASSWORD");
const superAdminUsername = requireDotenvValue(process.env.SUPER_ADMIN_USERNAME, "SUPER_ADMIN_USERNAME");
const superAdminPassword = requireDotenvValue(process.env.SUPER_ADMIN_PASSWORD, "SUPER_ADMIN_PASSWORD");
const emailMailbox = requireDotenvValue(process.env.KEYCLOAK_EMAIL_POLICY, "KEYCLOAK_EMAIL_POLICY") === "mailbox";
const emailSmtp = requireDotenvValue(process.env.KEYCLOAK_EMAIL_SMTP, "KEYCLOAK_EMAIL_SMTP") === "true";
const emailUpdate =
  requireDotenvValue(process.env.KEYCLOAK_EMAIL_UPDATE_ENABLED, "KEYCLOAK_EMAIL_UPDATE_ENABLED") === "true";
const mailboxAttribute = requireDotenvValue(
  process.env.KEYCLOAK_EMAIL_MAILBOX_ATTRIBUTE,
  "KEYCLOAK_EMAIL_MAILBOX_ATTRIBUTE",
);
const webmailBaseUrl = normalizeBaseUrl(process.env.WEBMAIL_BASE_URL);

const usersApi = `${issuerBaseUrl}/admin/realms/${encodeURIComponent(realmName)}/users`;
const UPDATE_EMAIL = "UPDATE_EMAIL";
const CONFIRMATION_MAIL = /verify|e-?mail/i;
const ACTION_TOKEN_LINK = "a[href*='/login-actions/action-token']";
const WITHOUT_SMTP = "KEYCLOAK_EMAIL_SMTP=false: without SMTP only an administrator changes the address";
const UPDATE_EMAIL_OFF =
  "KEYCLOAK_EMAIL_UPDATE_ENABLED=false: UPDATE_EMAIL is off while the realm federates LDAP, because Keycloak 26.8.2 answers it with HTTP 500 (duplicate firstName and lastName metadata from the full-name LDAP mapper; upstream issue to be filed)";

function isProfileRead(response) {
  const url = new URL(response.url());
  return (
    response.request().method() === "GET" &&
    response.ok() &&
    url.pathname.replace(/\/$/, "") === `/realms/${realmName}/account` &&
    url.searchParams.get("userProfileMetadata") === "true"
  );
}

async function signInToAccountConsole(page, options = {}) {
  await gotoOnion(page, `${appBaseUrl}/realms/${realmName}/account/`);
  const signInButton = page.locator("a, button").filter({ hasText: /sign\s*in|log\s*in|anmelden/i }).first();
  if ((await signInButton.count().catch(() => 0)) > 0) {
    await signInButton.click({ timeout: resolveTimeout(30_000) });
  }
  await performKeycloakLoginForm(page, biberUsername, biberPassword, options);
}

async function asSuperAdmin(browser, body) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const token = await keycloakAdminToken(context.request, issuerBaseUrl, superAdminUsername, superAdminPassword);
    return await body(context.request, { Authorization: `Bearer ${token}` });
  } finally {
    await context.close();
  }
}

async function biberRecord(request, headers) {
  const found = await request.get(`${usersApi}?username=${encodeURIComponent(biberUsername)}&exact=true`, {
    headers,
    timeout: resolveTimeout(30_000),
  });
  expect(found.status(), "the super administrator must find biber").toBe(200);
  const [match] = await found.json();
  expect(match, "biber must exist in the realm").toBeTruthy();
  const response = await request.get(`${usersApi}/${match.id}`, { headers, timeout: resolveTimeout(30_000) });
  expect(response.status(), "the super administrator must read biber").toBe(200);
  return response.json();
}

async function restoreBiber(browser, original) {
  await asSuperAdmin(browser, async (request, headers) => {
    const current = await biberRecord(request, headers);
    const attributes = Object.fromEntries(
      Object.entries(current.attributes || {}).filter(([name]) => !/pending/i.test(name)),
    );
    const response = await request.put(`${usersApi}/${current.id}`, {
      headers: { ...headers, "Content-Type": "application/json" },
      data: {
        ...current,
        email: original.email,
        emailVerified: original.emailVerified,
        attributes,
        requiredActions: (current.requiredActions || []).filter((action) => action !== UPDATE_EMAIL),
      },
      timeout: resolveTimeout(30_000),
    });
    expect(response.status(), "the super administrator must restore biber's address").toBe(204);
  });
}

async function expectBiberSignsInWithoutPendingChange(browser) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const page = await context.newPage();
    await signInToAccountConsole(page, { settle: false });
    await expect
      .poll(() => new URL(page.url()).pathname.startsWith(`/realms/${realmName}/account`), {
        timeout: resolveTimeout(60_000),
        message: "biber's next sign-in must reach the account console, not a pending UPDATE_EMAIL",
      })
      .toBe(true);
  } finally {
    await context.close();
  }
}

function subAddress(address) {
  const at = address.lastIndexOf("@");
  return `${address.slice(0, at)}+pending${Date.now().toString(36)}${address.slice(at)}`;
}

async function requestAddressChange(page, address) {
  const query = new URLSearchParams({
    client_id: "account",
    redirect_uri: `${appBaseUrl}/realms/${realmName}/account/`,
    response_type: "code",
    scope: "openid",
    kc_action: UPDATE_EMAIL,
  });
  await gotoOnion(page, `${appBaseUrl}/realms/${realmName}/protocol/openid-connect/auth?${query}`);
  await performKeycloakLoginForm(page, biberUsername, biberPassword, { settle: false });
  const field = page.locator("input[name='email']");
  await field.waitFor({ state: "visible", timeout: resolveTimeout(60_000) });
  await field.fill(address);
  await page.locator("button[type='submit'], input[type='submit']").first().click({ timeout: resolveTimeout(30_000) });
  await expect(
    page.locator("body"),
    `Keycloak must announce the confirmation link it sent to ${address}`,
  ).toContainText(address, { timeout: resolveTimeout(60_000) });
}

function tokenAddress(href) {
  const payload = (new URL(href).searchParams.get("key") || "").split(".")[1];
  return payload ? JSON.parse(Buffer.from(payload, "base64url").toString("utf8")).newEmail : null;
}

async function confirmationLink(page, address) {
  const deadline = Date.now() + resolveTimeout(180_000);
  while (Date.now() < deadline) {
    const row = await waitForEmailInMailbox(page, webmailBaseUrl, CONFIRMATION_MAIL, resolveTimeout(120_000));
    await row.click({ timeout: resolveTimeout(30_000) });
    const href =
      (await page
        .frameLocator("#messagecontframe")
        .locator(ACTION_TOKEN_LINK)
        .first()
        .getAttribute("href", { timeout: resolveTimeout(15_000) })
        .catch(() => null)) ||
      (await page
        .locator(ACTION_TOKEN_LINK)
        .first()
        .getAttribute("href", { timeout: resolveTimeout(5_000) })
        .catch(() => null));
    if (href && tokenAddress(href) === address) {
      return href;
    }
    await page.waitForTimeout(resolveTimeout(5_000));
  }
  throw new Error(`no confirmation mail for ${address} reached biber's mailbox`);
}

exports.register = function () {
  test("biber: email policy: biber cannot change the primary address directly", async ({ page }) => {
    skipUnlessServiceEnabled("ldap");
    test.setTimeout(resolveTimeout(180_000));
    const primary = emailMailbox ? mailboxAttribute : "email";
    const profileRead = page.waitForResponse(isProfileRead, { timeout: resolveTimeout(120_000) });

    await signInToAccountConsole(page);

    const profile = await (await profileRead).json();
    const attribute = ((profile.userProfileMetadata || {}).attributes || []).find(
      (candidate) => candidate.name === primary,
    );
    expect(attribute, `the account console MUST show biber the primary address attribute ${primary}`).toBeTruthy();
    expect(
      attribute.readOnly,
      `the account console MUST offer biber no direct edit of the primary address attribute ${primary}`,
    ).toBe(true);
  });

  test("biber: email policy: a requested change of the changeable address stays pending", async ({ browser }) => {
    skipUnlessServiceEnabled("ldap");
    test.skip(!emailSmtp, WITHOUT_SMTP);
    test.skip(!emailUpdate, UPDATE_EMAIL_OFF);
    test.setTimeout(resolveTimeout(300_000));
    const original = await asSuperAdmin(browser, biberRecord);
    expect(emailMailbox || original.email, "biber MUST hold a primary address under the external policy").toBeTruthy();
    const address = emailMailbox
      ? `${biberUsername}+pending${Date.now().toString(36)}@example.net`
      : subAddress(original.email);
    const context = await browser.newContext({ ignoreHTTPSErrors: true });
    try {
      await requestAddressChange(await context.newPage(), address);
      const pending = await asSuperAdmin(browser, biberRecord);
      expect(pending.email, "the changeable address MUST stay in force until the link is followed").toBe(
        original.email,
      );
    } finally {
      await context.close().catch(() => {});
      await restoreBiber(browser, original);
    }
    await expectBiberSignsInWithoutPendingChange(browser);
  });

  test("biber: email policy: following the confirmation link applies the pending address", async ({ browser }) => {
    skipUnlessServiceEnabled("ldap");
    test.skip(!emailSmtp, WITHOUT_SMTP);
    test.skip(!emailUpdate, UPDATE_EMAIL_OFF);
    test.skip(emailMailbox, "KEYCLOAK_EMAIL_POLICY=mailbox: the secondary address lies outside the mail domain, so no local mailbox receives the link");
    test.skip(!webmailBaseUrl, "WEBMAIL_BASE_URL is empty: the mail provider serves no webmail to read the link from");
    test.skip(isSplitRealmOidc(), "clearnet webmail with an onion OIDC issuer: unreachable from one browser");
    test.setTimeout(resolveTimeout(480_000));
    const original = await asSuperAdmin(browser, biberRecord);
    expect(original.email, "biber MUST hold a primary address to receive the link at").toBeTruthy();
    const address = subAddress(original.email);
    const context = await browser.newContext({ ignoreHTTPSErrors: true });
    try {
      const page = await context.newPage();
      await requestAddressChange(page, address);
      expect((await asSuperAdmin(browser, biberRecord)).email, "the old address MUST stay in force first").toBe(
        original.email,
      );
      const mail = await context.newPage();
      await webmailSsoLogin(mail, biberUsername, biberPassword, webmailBaseUrl);
      await gotoOnion(page, await confirmationLink(mail, address));
      const proceed = page.locator("a, button").filter({ hasText: /proceed|fortfahren/i }).first();
      if (await proceed.isVisible().catch(() => false)) {
        await proceed.click({ timeout: resolveTimeout(30_000) });
      }
      await expect
        .poll(async () => (await asSuperAdmin(browser, biberRecord)).email, {
          timeout: resolveTimeout(60_000),
          message: "following the confirmation link MUST apply the pending address",
        })
        .toBe(address);
    } finally {
      await context.close().catch(() => {});
      await restoreBiber(browser, original);
    }
    await expectBiberSignsInWithoutPendingChange(browser);
  });
};
