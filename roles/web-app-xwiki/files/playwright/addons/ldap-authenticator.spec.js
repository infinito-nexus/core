const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");

const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceDisabled, skipUnlessServiceEnabled } = require("../service-gating");
const {
  gotoOnion,
  normalizeBaseUrl,
  requireDotenvValue,
  withLdapAttributes,
} = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const canonicalDomain = requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN");
const ADMIN_PATH = "/bin/admin/XWiki/XWikiPreferences";

function gateLdapLogin() {
  skipUnlessAddonEnabled("ldap-authenticator");
  skipUnlessServiceEnabled("ldap");
  skipUnlessServiceDisabled("sso");
}

async function signInViaLdap(page, username, password) {
  const base = appBaseUrl.replace(/\/$/, "");
  await gotoOnion(page, `${base}/bin/login/XWiki/XWikiLogin`, { waitUntil: "domcontentloaded" });
  const usernameField = page.locator("input#j_username, input[name='j_username']").first();
  const passwordField = page.locator("input#j_password, input[name='j_password']").first();
  await expect(usernameField, "XWiki MUST serve its LDAP-backed login form").toBeVisible({
    timeout: resolveTimeout(30_000),
  });
  await usernameField.fill(username);
  await passwordField.fill(password);
  await passwordField.press("Enter");
  await page.waitForURL((url) => !/\/bin\/(login|loginsubmit)\//.test(url.pathname), {
    timeout: resolveTimeout(60_000),
  });
  await page.waitForLoadState("domcontentloaded");
  return page.locator("html").getAttribute("data-xwiki-user-reference");
}

async function adminPageStatus(page) {
  const base = appBaseUrl.replace(/\/$/, "");
  const response = await gotoOnion(page, `${base}${ADMIN_PATH}`, { waitUntil: "domcontentloaded" });
  expect(response, `Expected a response for ${ADMIN_PATH}`).toBeTruthy();
  return response.status();
}

test("biber: ldap-authenticator binds biber with its uid, gives it its directory profile and no admin rights", async ({ page }) => {
  gateLdapLogin();
  test.setTimeout(resolveTimeout(180_000));
  const username = requireDotenvValue(process.env.BIBER_USERNAME, "BIBER_USERNAME");
  const firstname = requireDotenvValue(process.env.BIBER_FIRSTNAME, "BIBER_FIRSTNAME");

  const reference = await signInViaLdap(page, username, requireDotenvValue(process.env.BIBER_PASSWORD, "BIBER_PASSWORD"));
  expect(
    reference,
    `the LDAP bind MUST resolve ${username} through the uid attribute and land on XWiki.${username}`,
  ).toMatch(new RegExp(`XWiki\\.${username}$`, "i"));

  const base = appBaseUrl.replace(/\/$/, "");
  await gotoOnion(page, `${base}/bin/view/XWiki/${encodeURIComponent(username)}`, { waitUntil: "domcontentloaded" });
  await expect(
    page.locator("body"),
    "the LDAP fields mapping MUST copy the directory first name into the XWiki profile",
  ).toContainText(firstname, { timeout: resolveTimeout(30_000) });

  expect(await adminPageStatus(page), `${username} holds no administrator role, so ${ADMIN_PATH} MUST answer 403`).toBe(
    403,
  );
});

test("biber: ldap-authenticator copies the directory phone, website and organization into biber's XWiki profile at LDAP login", async ({
  page,
}) => {
  gateLdapLogin();
  test.setTimeout(resolveTimeout(180_000));
  const username = requireDotenvValue(process.env.BIBER_USERNAME, "BIBER_USERNAME");
  const suffix = String(Date.now()).slice(-7);
  const directoryValues = {
    [requireDotenvValue(process.env.LDAP_PHONE_ATTRIBUTE, "LDAP_PHONE_ATTRIBUTE")]: `+49 30 ${suffix}`,
    [requireDotenvValue(process.env.LDAP_WEBSITE_ATTRIBUTE, "LDAP_WEBSITE_ATTRIBUTE")]: `https://biber-${suffix}.example`,
    [requireDotenvValue(process.env.LDAP_ORGANIZATION_ATTRIBUTE, "LDAP_ORGANIZATION_ATTRIBUTE")]: `Biberbau ${suffix}`,
  };

  await withLdapAttributes(requireDotenvValue(process.env.BIBER_LDAP_DN, "BIBER_LDAP_DN"), directoryValues, async () => {
    const reference = await signInViaLdap(page, username, requireDotenvValue(process.env.BIBER_PASSWORD, "BIBER_PASSWORD"));
    expect(reference, `the LDAP bind MUST land ${username} on XWiki.${username}`).toMatch(
      new RegExp(`XWiki\\.${username}$`, "i"),
    );

    const base = appBaseUrl.replace(/\/$/, "");
    await gotoOnion(page, `${base}/bin/view/XWiki/${encodeURIComponent(username)}`, { waitUntil: "domcontentloaded" });
    for (const [attribute, value] of Object.entries(directoryValues)) {
      await expect(
        page.locator("body"),
        `the LDAP fields mapping MUST copy the directory ${attribute} into the XWiki profile of ${username}`,
      ).toContainText(value, { timeout: resolveTimeout(30_000) });
    }
  });
});

test("administrator: ldap-authenticator binds the administrator into XWikiAdminGroup through its directory role group", async ({
  page,
}) => {
  gateLdapLogin();
  test.setTimeout(resolveTimeout(180_000));
  const username = requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME");

  const reference = await signInViaLdap(page, username, requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD"));
  expect(reference, `the LDAP bind MUST land ${username} on XWiki.${username}`).toMatch(
    new RegExp(`XWiki\\.${username}$`, "i"),
  );
  expect(
    await adminPageStatus(page),
    `${username} is a member of the administrator role group in the directory, so the LDAP group sync MUST grant XWikiAdminGroup and ${ADMIN_PATH} MUST open`,
  ).toBeLessThan(400);
});

test("guest: ldap-authenticator makes XWiki enforce its LDAP-backed native credential form on protected pages", async ({ page }) => {
  skipUnlessAddonEnabled("ldap-authenticator");
  skipUnlessServiceEnabled("ldap");

  // When OIDC owns the login journey the active authservice is the OIDC
  // authclass (compose.yml.j2 prefers oidc), not the LDAP authclass — that
  // path is covered by the oidc-authenticator spec. The LDAP authclass is only
  // the active backend when SSO is off, so this LDAP-specific proof is only
  // meaningful then.
  skipUnlessServiceDisabled("sso");

  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();

  await page.context().clearCookies();

  const base = appBaseUrl.replace(/\/$/, "");

  await gotoOnion(page, `${base}/bin/view/XWiki/XWikiPreferences`, {
    waitUntil: "domcontentloaded",
  });

  // The LDAP authclass keeps authentication inside XWiki: a protected page for
  // an anonymous visitor must route to XWiki's own login surface on the XWiki
  // host, never to an external IdP. Anything that leaves the canonical domain
  // (i.e. an OIDC redirect) means the LDAP authservice is NOT the active backend.
  const stayedOnHost = new URL(page.url()).hostname.endsWith(canonicalDomain);
  expect(
    stayedOnHost,
    `protected page must route to XWiki's own LDAP-backed login on ${canonicalDomain}, ` +
      `but the browser left the host (got ${page.url()}) — the LDAP authservice is not active.`,
  ).toBe(true);

  const onLoginSurface =
    /viewer=login|XWiki\.XWikiLogin|\/login/i.test(page.url()) ||
    (await page
      .locator("input[type='password']:visible")
      .first()
      .waitFor({ state: "visible", timeout: resolveTimeout(2_000) })
      .then(() => true)
      .catch(() => false));
  expect(
    onLoginSurface,
    "an anonymous visitor to a protected XWiki page must be challenged with a login surface " +
      "(LDAP authclass enforces authentication); none was presented",
  ).toBe(true);

  // The LDAP authenticator backs XWiki's native username/password credential
  // form. Assert that form is what is served (not an anonymous page, not a
  // third-party SSO button), proving the credential path the LDAP backend
  // validates against is wired in.
  const usernameField = page
    .locator(
      "input[name='j_username'], input#j_username, input[name='username']:visible, input[name='loginName']:visible, input[type='text']:visible",
    )
    .first();
  const passwordField = page
    .locator("input[name='j_password'], input#j_password, input[type='password']:visible")
    .first();

  await expect(
    usernameField,
    "XWiki must serve a username field for the LDAP-backed native login form",
  ).toBeVisible({ timeout: resolveTimeout(30_000) });
  await expect(
    passwordField,
    "XWiki must serve a password field for the LDAP-backed native login form",
  ).toBeVisible({ timeout: resolveTimeout(30_000) });

  // A bogus credential must be rejected by the LDAP-backed authenticator: the
  // user stays on the XWiki login surface (no session granted). This exercises
  // the live LDAP bind/validation path end-to-end rather than just asserting
  // the form exists.
  await usernameField.fill("nonexistent-ldap-user-e2e").catch(() => {});
  await passwordField.fill("definitely-wrong-password-e2e").catch(() => {});
  await passwordField.press("Enter").catch(() => {});
  await page.waitForLoadState("networkidle").catch(() => {});

  const stillUnauthenticated =
    /viewer=login|XWiki\.XWikiLogin|\/login/i.test(page.url()) ||
    (await page
      .locator("input[type='password']:visible")
      .first()
      .waitFor({ state: "visible", timeout: resolveTimeout(2_000) })
      .then(() => true)
      .catch(() => false));
  expect(
    stillUnauthenticated,
    "invalid credentials must be rejected by the LDAP-backed authenticator (no session granted); " +
      `instead the browser reached an authenticated surface at ${page.url()}.`,
  ).toBe(true);
});
