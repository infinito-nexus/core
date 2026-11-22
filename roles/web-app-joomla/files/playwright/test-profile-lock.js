const crypto = require("crypto");
const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const {
  decodeDotenvQuotedValue,
  gotoOnion,
  installCspViolationObserver,
  isAuthChain,
  normalizeBaseUrl,
  requireDotenvValue,
} = require("./personas");
const { signInToAdministrator, signInToSite, signInViaKeycloak, userManagerRow } = require("./joomla-session");

const base = normalizeBaseUrl(process.env.JOOMLA_BASE_URL);
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);
const catalogue = JSON.parse(requireDotenvValue(process.env.PROFILE_LOCK_I18N_JSON, "PROFILE_LOCK_I18N_JSON"));
const lockedSelectors = JSON.parse(
  requireDotenvValue(process.env.PROFILE_LOCK_SELECTORS_JSON, "PROFILE_LOCK_SELECTORS_JSON"),
);

const ACTION = { timeout: resolveTimeout(30_000) };
const PROFILE_EDIT = "index.php?option=com_users&view=profile&layout=edit";
const PROFILE_FORM = "form#member-profile";
const PROFILE_VIEW = "main .com-users-profile";
const SUCCESS_NOTICE = "#system-message-container joomla-alert[type='success']";
const LOCKED_FIELDS = {
  "jform[name]": "#jform_name",
  "jform[username]": "#jform_username",
  "jform[email1]": "#jform_email1",
};
const LOCKED_PROFILE_FIELD = "#jform_profile_phone";
const LOCKED_SELECT = "#jform_params_language";
const UNMANAGED_FIELD = "jform[params][editor]";
const UNMANAGED_SELECT = "#jform_params_editor";
const DEFAULT_EDITOR = "";
const SITE_EDITABLE = ["#jform_name", "#jform_email1"];
const ADMIN_EDITABLE = ["#jform_name", "#jform_username", "#jform_email"];
const SITE_LOGIN = "index.php?option=com_users&view=login&fallback=local";
const SITE_USERNAME = "main input[name='username']";
const SITE_PASSWORD = "main input[name='password']";
const SITE_SUBMIT = "main form button[type='submit'].btn-primary";
const USER_FORM = "form#user-form";
const USER_LIST = "form#adminForm #filter_search";

test.use({ ignoreHTTPSErrors: true });

/**
 * Args:
 *   page: Playwright page on a rendered Joomla page.
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
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  await installCspViolationObserver(page);
  return { context, page, errors };
}

async function closeSignedOut(context) {
  await context.clearCookies().catch(() => {});
  await context.close().catch(() => {});
}

/**
 * Args:
 *   page: Playwright page on a form of an account the lock applies to.
 *   warning: what expectedWarning returned for that page.
 */
async function expectEverySelectorLocked(page, warning) {
  for (const [field, selector] of Object.entries(lockedSelectors)) {
    const matches = page.locator(selector);
    await expect
      .poll(() => matches.count(), { message: `the sso field ${field} of meta/forms.yml must match a field of this form`, ...ACTION })
      .toBeGreaterThan(0);
    const count = await matches.count();
    for (let index = 0; index < count; index += 1) {
      await expect(matches.nth(index), `${field} must be read-only because the Keycloak login owns it`).not.toBeEditable(ACTION);
      await expect(matches.nth(index), `${field} must carry the profile lock warning`).toHaveAttribute("title", warning, ACTION);
    }
  }
}

/**
 * Args:
 *   page: Playwright page with an SSO session on the profile edit form.
 * Returns:
 *   object: the stored name, username and email by form field name, after asserting every lock and its warning.
 */
async function expectLockedProfile(page) {
  const warning = await expectedWarning(page);
  await expectEverySelectorLocked(page, warning);
  const stored = {};
  for (const [name, selector] of Object.entries(LOCKED_FIELDS)) {
    const field = page.locator(`${PROFILE_FORM} ${selector}`);
    await expect(field, `${selector} must be read-only because the Keycloak login owns it`).not.toBeEditable(ACTION);
    await expect(field, `${selector} must carry the profile lock warning in the page language`).toHaveAttribute(
      "title",
      warning,
      ACTION,
    );
    stored[name] = await field.inputValue();
  }
  const profileField = page.locator(`${PROFILE_FORM} ${LOCKED_PROFILE_FIELD}`);
  await expect(profileField, "the plg_user_profile phone must be read-only").not.toBeEditable(ACTION);
  await expect(profileField, "the plg_user_profile phone must carry the warning").toHaveAttribute("title", warning, ACTION);
  const select = page.locator(`${PROFILE_FORM} ${LOCKED_SELECT}`);
  await expect(select, "the frontend language must be locked").toBeDisabled(ACTION);
  await expect(select, "the frontend language must carry the warning").toHaveAttribute("title", warning, ACTION);
  return stored;
}

/**
 * Args:
 *   page: Playwright page on the profile edit form whose lock was asserted.
 * Returns:
 *   string: an editor the form offers other than the stored one.
 */
async function otherEditor(page) {
  const editor = page.locator(`${PROFILE_FORM} ${UNMANAGED_SELECT}`);
  await expect(editor, "the profile must offer the unmanaged editor setting").toBeEditable(ACTION);
  const choice = await editor.evaluate((select) => {
    const option = Array.from(select.options).find((candidate) => candidate.value !== select.value);
    return option ? option.value : null;
  });
  expect(choice, "the editor setting must offer a second value to prove an unmanaged field still saves").not.toBeNull();
  return choice;
}

/**
 * Args:
 *   page: Playwright page on the profile edit form; ends on that form again once Joomla confirmed the save.
 *   values: the form fields the direct POST overrides.
 */
async function postProfile(page, values) {
  const form = await page.locator(PROFILE_FORM).evaluate((element) => ({
    action: element.action,
    fields: Object.fromEntries(new FormData(element).entries()),
  }));
  const response = await page.request.post(form.action, {
    form: { ...form.fields, task: "profile.save", ...values },
    maxRedirects: 0,
    timeout: resolveTimeout(60_000),
  });
  const location = response.headers().location;
  expect(location, `Joomla must answer the profile POST with a redirect, got ${response.status()}`).toBeTruthy();
  await gotoOnion(page, new URL(location, form.action).toString());
  await expect(page.locator(SUCCESS_NOTICE).first(), "Joomla must confirm the saved profile").toBeVisible(ACTION);
  await expect(page.locator(PROFILE_VIEW).first(), "a saved profile lands on the profile view, a refused one on the form").toBeVisible(ACTION);
  await gotoOnion(page, `${base}/${PROFILE_EDIT}`);
}

/**
 * Args:
 *   page: Playwright page with a site session of the account; ends on its profile edit form with the editor on
 *     DEFAULT_EDITOR.
 */
async function restoreDefaultEditor(page) {
  await gotoOnion(page, `${base}/${PROFILE_EDIT}`);
  await postProfile(page, { [UNMANAGED_FIELD]: DEFAULT_EDITOR });
  await expect(
    page.locator(`${PROFILE_FORM} ${UNMANAGED_SELECT}`),
    "the account must be back on the site default editor, which every later spec of it opens",
  ).toHaveValue(DEFAULT_EDITOR, ACTION);
}

/**
 * Args:
 *   page: Playwright page on the profile edit form whose lock was asserted; ends with the editor on DEFAULT_EDITOR,
 *     also when an assertion fails, whose error then propagates.
 *   stored: what expectLockedProfile returned.
 *   values: the form fields the direct POST overrides.
 */
async function expectDirectSaveKeeps(page, stored, values) {
  let failure = null;
  try {
    const editor = await otherEditor(page);
    await postProfile(page, { ...values, [UNMANAGED_FIELD]: editor });
    for (const [name, selector] of Object.entries(LOCKED_FIELDS)) {
      await expect(page.locator(`${PROFILE_FORM} ${selector}`), `a direct profile POST must not change ${selector}`).toHaveValue(
        stored[name],
        ACTION,
      );
    }
    await expect(
      page.locator(`${PROFILE_FORM} ${UNMANAGED_SELECT}`),
      "the same POST must still save the editor, which Keycloak does not manage",
    ).toHaveValue(editor, ACTION);
  } catch (error) {
    failure = error;
    throw error;
  } finally {
    await restoreDefaultEditor(page).catch((error) => {
      throw failure
        ? new AggregateError([failure, error], `${failure.message}\nrestoring the default editor failed too: ${error.message}`)
        : error;
    });
  }
}

test("biber: the Joomla profile locks name, username and email with the translated warning, and a direct save keeps them", async ({
  browser,
}) => {
  skipUnlessServiceEnabled("sso");
  skipUnlessServiceEnabled("javascript");
  test.setTimeout(resolveTimeout(180_000));
  expect(base, "JOOMLA_BASE_URL must be set").toBeTruthy();

  const session = await newSession(browser);
  const { page } = session;
  try {
    await signInViaKeycloak(page, base, biberUsername, biberPassword);
    await gotoOnion(page, `${base}/${PROFILE_EDIT}`);
    const stored = await expectLockedProfile(page);
    const suffix = String(Date.now()).slice(-6);
    await expectDirectSaveKeeps(page, stored, {
      "jform[name]": `${stored["jform[name]"]} tampered`,
      "jform[username]": `${stored["jform[username]"]}-tampered-${suffix}`,
      "jform[email1]": `tampered-${suffix}@example.invalid`,
    });
    expect(session.errors, "the injected lock renderer must not throw").toEqual([]);
  } finally {
    await closeSignedOut(session.context);
  }
});

test("administrator: the SSO administrator cannot rename itself, a direct profile save keeps its Keycloak username", async ({
  browser,
}) => {
  skipUnlessServiceEnabled("sso");
  skipUnlessServiceEnabled("javascript");
  test.setTimeout(resolveTimeout(180_000));
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();

  const session = await newSession(browser);
  const { page } = session;
  try {
    await signInViaKeycloak(page, base, adminUsername, adminPassword);
    await gotoOnion(page, `${base}/${PROFILE_EDIT}`);
    const stored = await expectLockedProfile(page);
    expect(stored["jform[username]"], "the SSO administrator's profile must show its Keycloak username").toBe(adminUsername);
    await expectDirectSaveKeeps(page, stored, {
      "jform[username]": `${adminUsername}-renamed-${String(Date.now()).slice(-6)}`,
    });
    expect(session.errors, "the injected lock renderer must not throw").toEqual([]);
  } finally {
    await closeSignedOut(session.context);
  }
});

test("administrator: a local break-glass session edits its own profile and its account in the backend without the SSO lock", async ({
  browser,
}) => {
  skipUnlessServiceEnabled("sso");
  skipUnlessServiceEnabled("javascript");
  test.setTimeout(resolveTimeout(180_000)); // one local site sign-in, one local administrator sign-in and two form renders
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();

  const site = await newSession(browser);
  try {
    await signInToSite(site.page, base, adminUsername, adminPassword);
    await gotoOnion(site.page, `${base}/${PROFILE_EDIT}`);
    const warning = await expectedWarning(site.page);
    for (const selector of SITE_EDITABLE) {
      const field = site.page.locator(`${PROFILE_FORM} ${selector}`);
      await expect(field, `a local session must edit ${selector} on the site profile`).toBeEditable(ACTION);
      await expect(field, `${selector} must not carry the SSO lock warning in a local session`).not.toHaveAttribute(
        "title",
        warning,
      );
    }
    expect(site.errors, "the injected lock renderer must not throw").toEqual([]);
  } finally {
    await closeSignedOut(site.context);
  }

  const backend = await newSession(browser);
  try {
    await signInToAdministrator(backend.page, base, adminUsername, adminPassword);
    const row = await userManagerRow(backend.page, base, adminUsername);
    await row.locator("a[href*='task=user.edit']").first().click(ACTION);
    const warning = await expectedWarning(backend.page);
    for (const selector of ADMIN_EDITABLE) {
      const field = backend.page.locator(`${USER_FORM} ${selector}`);
      await expect(field, `the break-glass administrator must edit ${selector}`).toBeEditable(ACTION);
      await expect(field, `${selector} must not carry the SSO lock warning in a local session`).not.toHaveAttribute(
        "title",
        warning,
      );
    }
    expect(backend.errors, "the injected lock renderer must not throw").toEqual([]);
  } finally {
    await closeSignedOut(backend.context);
  }
});

test("biber: a local password on the SSO account opens no ?fallback=local session, the sign-in goes to Keycloak instead", async ({
  browser,
}) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(240_000)); // one OIDC round-trip, one backend password save and one refused local sign-in
  expect(biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
  const localPassword = `Local-${crypto.randomBytes(18).toString("base64url")}-9a`;

  const sso = await newSession(browser);
  try {
    await signInViaKeycloak(sso.page, base, biberUsername, biberPassword);
  } finally {
    await closeSignedOut(sso.context);
  }

  const backend = await newSession(browser);
  try {
    await signInToAdministrator(backend.page, base, adminUsername, adminPassword);
    const row = await userManagerRow(backend.page, base, biberUsername);
    await row.locator("a[href*='task=user.edit']").first().click(ACTION);
    await expect(backend.page.locator(`${USER_FORM} #jform_password`)).toBeEditable(ACTION);
    await backend.page.locator(`${USER_FORM} #jform_password`).fill(localPassword);
    await backend.page.locator(`${USER_FORM} #jform_password2`).fill(localPassword);
    await backend.page.evaluate(() => window.Joomla.submitbutton("user.save"));
    await expect(backend.page.locator(USER_LIST), "Save & Close must return to Users: Manage").toBeVisible(ACTION);
    await expect(
      backend.page.locator(SUCCESS_NOTICE).first(),
      "the break-glass administrator must give biber a local password in the backend",
    ).toBeVisible(ACTION);
  } finally {
    await closeSignedOut(backend.context);
  }

  const local = await newSession(browser);
  const { page } = local;
  try {
    await gotoOnion(page, `${base}/${SITE_LOGIN}`);
    await expect(page.locator(SITE_USERNAME), "the ?fallback=local form must render").toBeEditable(ACTION);
    await page.locator(SITE_USERNAME).fill(biberUsername);
    await page.locator(SITE_PASSWORD).fill(localPassword);
    await page.locator(SITE_SUBMIT).first().click(ACTION);
    await expect
      .poll(() => isAuthChain(page.url()), {
        message: "plg_system_keycloak must sign the SSO account out again and send it to Keycloak",
        ...ACTION,
      })
      .toBe(true);
    await gotoOnion(page, `${base}/index.php?option=com_users&view=profile`);
    await expect(page.locator(PROFILE_VIEW), "biber must hold no Joomla session after the local sign-in").toHaveCount(0);
  } finally {
    await closeSignedOut(local.context);
  }
});
