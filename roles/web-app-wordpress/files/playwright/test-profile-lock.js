const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { gotoOnion, installCspViolationObserver, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

const catalogue = JSON.parse(requireDotenvValue(process.env.PROFILE_LOCK_I18N_JSON, "PROFILE_LOCK_I18N_JSON"));
const lockedSelectors = JSON.parse(
  requireDotenvValue(process.env.PROFILE_LOCK_SELECTORS_JSON, "PROFILE_LOCK_SELECTORS_JSON"),
);

const ACTION = { timeout: resolveTimeout(30_000) };
const PROFILE_FORM = "form#your-profile";
const READ_ONLY = {
  first_name: "input#first_name",
  last_name: "input#last_name",
  email: "input#email",
  url: "input#url",
};
const DISABLED = ["select#display_name"];
const UNMANAGED = "textarea#description";
const SAVED_NOTICE = "#message.updated";
const ROW_ONLY_WITH_LANGUAGE_PACKS = { language: "tr.user-language-wrap" };

/**
 * Args:
 *   page: Playwright page on a rendered WordPress admin page.
 * Returns:
 *   string: the warning the shared lock renderer shows in the page's language.
 */
async function expectedWarning(page) {
  const tags = await page.evaluate(() => [document.documentElement.lang, navigator.language]);
  for (const raw of tags) {
    const tag = String(raw || "").toLowerCase();
    const entry = catalogue[tag] || catalogue[tag.split("-")[0]];
    if (entry) return entry.locked;
  }
  return catalogue.en.locked;
}

async function newSession(browser) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 1100 } });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  await installCspViolationObserver(page);
  return { context, page, errors };
}

/**
 * Args:
 *   page: Playwright page on profile.php or user-edit.php of an OIDC account.
 *   warning: what expectedWarning returned for that page.
 */
async function expectEverySelectorLocked(page, warning) {
  for (const [field, selector] of Object.entries(lockedSelectors)) {
    const row = ROW_ONLY_WITH_LANGUAGE_PACKS[field];
    if (row && (await page.locator(row).count()) === 0) continue;
    const matches = page.locator(selector);
    await expect
      .poll(() => matches.count(), { message: `the sso field ${field} of meta/forms.yml must match a field of this form`, ...ACTION })
      .toBeGreaterThan(0);
    const count = await matches.count();
    for (let index = 0; index < count; index += 1) {
      await expect(matches.nth(index), `${field} must be locked because the OIDC login overwrites it`).not.toBeEditable(ACTION);
      await expect(matches.nth(index), `${field} must carry the profile lock warning`).toHaveAttribute("title", warning, ACTION);
    }
  }
}

/**
 * Args:
 *   page: Playwright page on profile.php or user-edit.php of an OIDC account.
 * Returns:
 *   object: the stored value of every read-only field, after asserting the lock and its warning.
 */
async function expectLockedProfile(page) {
  const warning = await expectedWarning(page);
  await expectEverySelectorLocked(page, warning);
  const stored = {};
  for (const [name, selector] of Object.entries(READ_ONLY)) {
    const field = page.locator(`${PROFILE_FORM} ${selector}`);
    await expect(field, `${selector} must be read-only because the OIDC login overwrites it`).not.toBeEditable(ACTION);
    await expect(field, `${selector} must carry the profile lock warning in the page language`).toHaveAttribute(
      "title",
      warning,
      ACTION,
    );
    stored[name] = await field.inputValue();
  }
  for (const selector of DISABLED) {
    const field = page.locator(`${PROFILE_FORM} ${selector}`);
    await expect(field, `${selector} must be locked because the OIDC login overwrites it`).toBeDisabled(ACTION);
    await expect(field, `${selector} must carry the profile lock warning in the page language`).toHaveAttribute(
      "title",
      warning,
      ACTION,
    );
  }
  return stored;
}

async function expectStoredProfile(page, stored, how) {
  for (const [name, selector] of Object.entries(READ_ONLY)) {
    await expect(page.locator(`${PROFILE_FORM} ${selector}`), `${how} must not change ${selector}`).toHaveValue(
      stored[name],
      ACTION,
    );
  }
}

function tampered(stored) {
  const suffix = String(Date.now()).slice(-6);
  return {
    first_name: `${stored.first_name}-tampered`,
    last_name: `${stored.last_name}-tampered`,
    email: `tampered-${suffix}@example.invalid`,
    url: `https://tampered-${suffix}.example.invalid`,
  };
}

/**
 * Args:
 *   page: Playwright page with a WordPress session.
 *   base: WordPress base URL.
 * Returns:
 *   string: the wp_rest nonce of the signed-in account.
 */
async function restNonce(page, base) {
  const response = await page.request.get(`${base}/wp-admin/admin-ajax.php?action=rest-nonce`, ACTION);
  expect(response.ok(), "admin-ajax must hand the signed-in account its REST nonce").toBe(true);
  return (await response.text()).trim();
}

function xmlText(value) {
  return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/**
 * Args:
 *   username: account the call authenticates as.
 *   password: its application password.
 *   fields: wp.editProfile content struct.
 * Returns:
 *   string: the XML-RPC request body of wp.editProfile on blog 1.
 */
function editProfileCall(username, password, fields) {
  const members = Object.entries(fields)
    .map(([name, value]) => `<member><name>${name}</name><value><string>${xmlText(value)}</string></value></member>`)
    .join("");
  return (
    '<?xml version="1.0"?><methodCall><methodName>wp.editProfile</methodName><params>' +
    "<param><value><int>1</int></value></param>" +
    `<param><value><string>${xmlText(username)}</string></value></param>` +
    `<param><value><string>${xmlText(password)}</string></value></param>` +
    `<param><value><struct>${members}</struct></value></param>` +
    "</params></methodCall>"
  );
}

exports.register = function (shared) {
  test("biber: profile.php locks the Keycloak fields with the translated warning, and a direct REST update keeps them", async ({
    browser,
  }) => {
    skipUnlessServiceEnabled("sso");
    skipUnlessServiceEnabled("javascript");
    test.setTimeout(resolveTimeout(180_000)); // one OIDC round-trip, one REST update and two profile renders
    const { env } = shared;
    const session = await newSession(browser);
    const { page } = session;
    try {
      await shared.wpAdminLoginViaOidc(page, env.wpBaseUrl, env.biberUsername, env.biberPassword);
      await gotoOnion(page, `${env.wpBaseUrl}/wp-admin/profile.php`, { waitUntil: "domcontentloaded" });
      const stored = await expectLockedProfile(page);

      const values = tampered(stored);
      const response = await page.request.post(`${env.wpBaseUrl}/?rest_route=/wp/v2/users/me`, {
        headers: { "X-WP-Nonce": await restNonce(page, env.wpBaseUrl) },
        data: { ...values, name: `${values.first_name} ${values.last_name}` },
        timeout: resolveTimeout(60_000),
      });
      expect(response.ok(), `the REST users endpoint must answer the update: ${response.status()}`).toBe(true);

      await gotoOnion(page, `${env.wpBaseUrl}/wp-admin/profile.php`, { waitUntil: "domcontentloaded" });
      await expectStoredProfile(page, stored, "a direct /wp/v2/users/me update");
      expect(session.errors, "the injected lock renderer must not throw").toEqual([]);
      await shared.wpSignOut(page, env.wpBaseUrl);
    } finally {
      await session.context.close().catch(() => {});
    }
  });

  test("biber: an XML-RPC wp.editProfile with an application password keeps the Keycloak fields", async ({ browser }) => {
    skipUnlessServiceEnabled("sso");
    skipUnlessServiceEnabled("javascript");
    test.setTimeout(resolveTimeout(180_000)); // one OIDC round-trip, the application password round-trip and one XML-RPC call
    const { env } = shared;
    const session = await newSession(browser);
    const { page } = session;
    let passwords = null;
    try {
      await shared.wpAdminLoginViaOidc(page, env.wpBaseUrl, env.biberUsername, env.biberPassword);
      await gotoOnion(page, `${env.wpBaseUrl}/wp-admin/profile.php`, { waitUntil: "domcontentloaded" });
      const stored = await expectLockedProfile(page);

      const nonce = await restNonce(page, env.wpBaseUrl);
      passwords = { nonce, route: `${env.wpBaseUrl}/?rest_route=/wp/v2/users/me/application-passwords` };
      const created = await page.request.post(passwords.route, {
        headers: { "X-WP-Nonce": nonce },
        data: { name: `profile-lock-${Date.now()}` },
        timeout: resolveTimeout(60_000),
      });
      if (new URL(env.wpBaseUrl).protocol !== "https:") {
        expect(created.status(), "WordPress must refuse an application password over plain HTTP").toBe(501);
        expect((await created.json()).code, "the refusal must be the site-wide HTTPS gate, not a per-user one").toBe(
          "application_passwords_disabled",
        );
        return;
      }
      expect(created.ok(), `WordPress must issue biber an application password: ${created.status()}`).toBe(true);
      const issued = await created.json();
      passwords.uuid = issued.uuid;

      const values = tampered(stored);
      const call = await page.request.post(`${env.wpBaseUrl}/xmlrpc.php`, {
        headers: { "Content-Type": "text/xml" },
        data: editProfileCall(env.biberUsername, issued.password, {
          first_name: values.first_name,
          last_name: values.last_name,
          url: values.url,
          display_name: `${values.first_name} ${values.last_name}`,
        }),
        timeout: resolveTimeout(60_000),
      });
      expect(call.ok(), `xmlrpc.php must answer wp.editProfile: ${call.status()}`).toBe(true);
      const answer = await call.text();
      expect(answer, "wp.editProfile must not answer with an XML-RPC fault").not.toContain("<fault>");
      expect(answer, "wp.editProfile must report success, the mu-plugin keeps the managed values").toMatch(
        /<boolean>\s*1\s*<\/boolean>/,
      );

      await gotoOnion(page, `${env.wpBaseUrl}/wp-admin/profile.php`, { waitUntil: "domcontentloaded" });
      await expectStoredProfile(page, stored, "an XML-RPC wp.editProfile");
      expect(session.errors, "the injected lock renderer must not throw").toEqual([]);
    } finally {
      if (passwords && passwords.uuid) {
        await page.request
          .delete(`${passwords.route}/${passwords.uuid}`, {
            headers: { "X-WP-Nonce": passwords.nonce },
            timeout: resolveTimeout(30_000),
          })
          .catch((error) => console.warn(`Revoking biber's application password failed: ${error}`));
      }
      await shared.wpSignOut(page, env.wpBaseUrl).catch(() => {});
      await session.context.close().catch(() => {});
    }
  });

  test("administrator: user-edit.php locks biber's Keycloak fields with the translated warning, and a direct save keeps them", async ({
    browser,
  }) => {
    skipUnlessServiceEnabled("sso");
    skipUnlessServiceEnabled("javascript");
    test.setTimeout(resolveTimeout(240_000)); // two OIDC round-trips, one user-edit POST and three user-edit renders
    const { env } = shared;
    const biber = await newSession(browser);
    try {
      await shared.wpAdminLoginViaOidc(biber.page, env.wpBaseUrl, env.biberUsername, env.biberPassword);
    } finally {
      await biber.context.close().catch(() => {});
    }

    const session = await newSession(browser);
    const { page } = session;
    try {
      await shared.wpAdminLogin(page);
      const users = env.multisiteEnabled ? "wp-admin/network/users.php" : "wp-admin/users.php";
      await gotoOnion(page, `${env.wpBaseUrl}/${users}?s=${encodeURIComponent(env.biberUsername)}`, {
        waitUntil: "domcontentloaded",
      });
      await page
        .locator("#the-list tr")
        .filter({ hasText: env.biberUsername })
        .locator("a[href*='user-edit.php']")
        .first()
        .click(ACTION);
      await expect(page.locator(PROFILE_FORM), "user-edit.php must render biber's profile form").toBeVisible(ACTION);
      const stored = await expectLockedProfile(page);

      const editUrl = page.url();
      const form = await page.locator(PROFILE_FORM).evaluate((element) => ({
        action: new URL(element.getAttribute("action"), element.baseURI).href,
        fields: Object.fromEntries(new FormData(element).entries()),
      }));
      const description = `profile-lock ${Date.now()}`;
      const response = await page.request.post(form.action, {
        form: { ...form.fields, ...tampered(stored), description },
        maxRedirects: 0,
        timeout: resolveTimeout(60_000),
      });
      const location = response.headers().location;
      expect(location, `user-edit.php must redirect after a saved profile, got ${response.status()}`).toBeTruthy();
      const saved = new URL(location, form.action).toString();
      expect(saved, "user-edit.php redirects with updated=1 only after a successful save").toContain("updated=");
      await gotoOnion(page, saved, { waitUntil: "domcontentloaded" });
      await expect(page.locator(SAVED_NOTICE).first(), "user-edit.php must confirm the save").toBeVisible(ACTION);

      await gotoOnion(page, editUrl, { waitUntil: "domcontentloaded" });
      await expectStoredProfile(page, stored, "a direct user-edit.php save");
      await expect(
        page.locator(`${PROFILE_FORM} ${UNMANAGED}`),
        "the same save must still change the biography, which Keycloak does not manage",
      ).toHaveValue(description, ACTION);
      expect(session.errors, "the injected lock renderer must not throw").toEqual([]);
      await shared.wpSignOut(page, env.wpBaseUrl);
    } finally {
      await session.context.close().catch(() => {});
    }
  });
};
