const crypto = require("crypto");
const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceDisabled } = require("./service-gating");
const { gotoOnion, recordVideoOptions, requireDotenvValue } = require("./personas");
const { totpCode } = require("./totp");

const ACTION = { timeout: resolveTimeout(30_000) };
const LANDING = { timeout: resolveTimeout(60_000) };
const SETTINGS_SAVE = "form#adminsettings button[type='submit']";
const SETTINGS_SAVED = ".alert-success";
const SETUP_PAGE = /\/admin\/tool\/mfa\/user_preferences\.php/;
const ENROLLED_PAGE = /\/admin\/tool\/mfa\/user_preferences\.php\?.*\baction=setup\b/;
const DASHBOARD = /\/my\/(index\.php)?$/;
const LOGIN_PAGE = "/login/index.php";
const COHORT = {
  enabled: "#id_s_factor_cohort_enabled",
  cohorts: "#id_s_factor_cohort_cohorts",
};
const GRACE = {
  enabled: "#id_s_factor_grace_enabled",
  forcesetup: "#id_s_factor_grace_forcesetup",
};
const NOSETUP = { enabled: "#id_s_factor_nosetup_enabled" };
const FIRST_SIGN_IN = { enabled: "#id_s_local_mfaenforce_enabled" };

function twoFactorEnabled() {
  return requireDotenvValue(process.env.LOGIN_METHOD_2FA_ENABLED, "LOGIN_METHOD_2FA_ENABLED") === "true";
}

/**
 * @param {import('@playwright/test').Page} page page of a signed-in administrator
 * @param {string} methodname Moodle web-service function that core/ajax may call
 * @param {object} args its arguments
 * @returns {Promise<any>} the function's answer
 */
async function ajax(page, methodname, args) {
  return page.evaluate(
    ({ name, parameters }) =>
      new Promise((resolve, reject) => {
        window.require(["core/ajax"], (moodleAjax) => {
          moodleAjax.call([{ methodname: name, args: parameters }])[0].then(resolve, (error) => reject(new Error(JSON.stringify(error))));
        });
      }),
    { name: methodname, parameters: args },
  );
}

/**
 * @param {import('@playwright/test').Locator} field admin setting field
 * @returns {Promise<boolean|string|string[]>} its current value
 */
async function readField(field) {
  return field.evaluate((element) => {
    if (element.type === "checkbox") return element.checked;
    if (element.multiple) return Array.from(element.selectedOptions, (option) => option.value).sort();
    return element.value;
  });
}

/**
 * @param {import('@playwright/test').Page} page page of a signed-in administrator
 * @param {string} base Moodle base URL
 * @param {string} section admin settings section of one plugin
 * @param {Object<string, boolean|string|string[]>} values wanted value per field selector
 * @param {Array<[string, object]>} restore list that receives the section and its previous values before the save
 */
async function configure(page, base, section, values, restore) {
  await gotoOnion(page, `${base}/admin/settings.php?section=${section}`, { waitUntil: "domcontentloaded" });
  const previous = {};
  for (const [selector, value] of Object.entries(values)) {
    const field = page.locator(selector);
    await expect(field, `${section} must offer ${selector}`).toBeAttached(ACTION);
    previous[selector] = await readField(field);
    if (typeof value === "boolean") {
      await field.setChecked(value, ACTION);
    } else if (await field.evaluate((element) => element.tagName === "SELECT")) {
      await field.selectOption(value, ACTION);
    } else {
      await field.fill(value, ACTION);
    }
  }
  const wanted = Object.fromEntries(Object.entries(values).map(([selector, value]) => [selector, Array.isArray(value) ? [...value].sort() : value]));
  if (JSON.stringify(previous) === JSON.stringify(wanted)) {
    return;
  }
  restore.unshift([section, previous]);
  await page.locator(SETTINGS_SAVE).first().click(ACTION);
  await expect(page.locator(SETTINGS_SAVED).filter({ hasText: /changes saved/i }), `${section} must save`).toBeVisible(ACTION);
}

/**
 * @param {import('@playwright/test').Page} page page of a signed-in administrator
 * @param {string} base Moodle base URL
 * @param {string} username login name of the new account
 * @param {string} label words its last name carries, the search key of the cohort form included
 * @returns {Promise<{id: number, username: string, password: string}>} the created account
 */
async function createAccount(page, base, username, label) {
  const password = `${crypto.randomBytes(24).toString("base64url")}Aa1-`;
  const email = `${username}@${requireDotenvValue(process.env.DOMAIN_PRIMARY, "DOMAIN_PRIMARY")}`;
  await gotoOnion(page, `${base}/user/editadvanced.php?id=-1`, { waitUntil: "domcontentloaded" });
  await expect(page.locator("#id_username"), "the new user form must render").toBeEditable(ACTION);
  await page.locator("#id_username").fill(username);
  const unmask = page.locator("[data-passwordunmaskid='id_newpassword'] [data-passwordunmask='edit']");
  if (await unmask.isVisible()) {
    await unmask.click(ACTION);
  }
  await page.locator("#id_newpassword").fill(password, ACTION);
  await page.locator("#id_firstname").fill("Infinito");
  await page.locator("#id_lastname").fill(label);
  await page.locator("#id_email").fill(email);
  await expect(page.locator("#id_email"), `the email field must hold all of ${email}`).toHaveValue(email, ACTION);
  await page.locator("#id_submitbutton").click(ACTION);
  await page.waitForURL((url) => !url.pathname.endsWith("/user/editadvanced.php"), ACTION);
  const users = await ajax(page, "core_user_get_users_by_field", { field: "username", values: [username] });
  expect(users, `the administrator must create ${username}`).toHaveLength(1);
  return { id: users[0].id, username, password };
}

/**
 * @param {import('@playwright/test').Page} page page of an account right after its sign-in
 * @param {string} base Moodle base URL
 * @param {string} who the account, as the failure message names it
 */
async function expectDashboard(page, base, who) {
  await page.waitForURL((url) => !url.pathname.endsWith(LOGIN_PAGE), LANDING);
  await gotoOnion(page, `${base}/my/`, { waitUntil: "domcontentloaded" });
  await expect(page, `${who} must reach the dashboard`).toHaveURL(DASHBOARD, LANDING);
}

/**
 * @param {import('@playwright/test').Page} page page of an account right after its sign-in
 * @param {string} base Moodle base URL
 * @param {string} who the account, as the failure message names it
 */
async function expectSetupThenEnrol(page, base, who) {
  await expect(page, `${who} without a factor must land on the MFA setup at this sign-in`).toHaveURL(SETUP_PAGE, LANDING);
  await expect(
    page.getByText(/you must complete setup for multi-factor authentication before you can proceed/i).first(),
    `the setup page must tell ${who} that the setup is required`,
  ).toBeVisible(ACTION);
  await gotoOnion(page, `${base}/my/`, { waitUntil: "domcontentloaded" });
  await expect(page, `the dashboard must hand ${who} back to the MFA setup`).toHaveURL(SETUP_PAGE, LANDING);

  const offer = page.getByRole("button", { name: /set up authenticator app/i }).or(page.getByRole("link", { name: /set up authenticator app/i })).first();
  await expect(offer, `the setup page must offer ${who} the authenticator app`).toBeVisible(ACTION);
  await offer.click(ACTION);
  await expect(page.locator("#id_devicename"), "the authenticator form must render").toBeEditable(ACTION);
  await page.locator("#id_devicename").fill("Infinito probe");
  const secret = await page.locator("input[name='secret']").inputValue();
  await page.locator("#id_verificationcode").fill(totpCode(secret));
  await page.locator("#id_submitbutton").click(ACTION);
  await expect(page, `${who} must get back to the factor list with the authenticator set up`).toHaveURL(ENROLLED_PAGE, LANDING);
  await gotoOnion(page, `${base}/my/`, { waitUntil: "domcontentloaded" });
  await expect(page, `${who} with an enrolled authenticator must reach the dashboard`).toHaveURL(DASHBOARD, LANDING);
}

exports.register = function (shared) {
  test("2fa enrollment: with its own second factor enforced Moodle sends a fresh and an existing account without one to setup at the first sign-in, the administrator included", async ({ browser, page }, testInfo) => {
    skipUnlessServiceDisabled("sso");
    test.skip(!twoFactorEnabled(), "LOGIN_METHOD_2FA_ENABLED=false");
    test.setTimeout(resolveTimeout(600_000));

    const base = shared.env.moodleBaseUrl;
    const suffix = `${Date.now().toString(36)}${crypto.randomBytes(3).toString("hex")}`;
    const cohortName = `Infinito 2FA probe ${suffix}`;

    await shared.loginAsSiteAdmin(page);
    const accounts = [];
    const restore = [];
    let cohortId = null;
    let administratorId = null;
    const signIn = async (account, check) => {
      const context = await browser.newContext({ ignoreHTTPSErrors: true, proxy: testInfo.project.use.proxy, ...recordVideoOptions(testInfo) });
      try {
        const own = await context.newPage();
        await shared.submitLoginForm(own, account.username, account.password);
        await check(own);
      } finally {
        await context.close();
      }
    };
    try {
      for (const role of ["fresh", "existing", "administrator", "late"]) {
        accounts.push(await createAccount(page, base, `infinito-2fa-${role}-${suffix}`, `2FA ${role} probe ${suffix}`));
      }
      const [fresh, existing, administrator, late] = accounts;

      await gotoOnion(page, `${base}/cohort/edit.php?contextid=1`, { waitUntil: "domcontentloaded" });
      await expect(page.locator("#id_name"), "the new cohort form must render").toBeEditable(ACTION);
      await page.locator("#id_name").fill(cohortName);
      await page.locator("#id_submitbutton").click(ACTION);
      await page.waitForURL((url) => !url.pathname.endsWith("/cohort/edit.php"), ACTION);
      const found = await ajax(page, "core_cohort_search_cohorts", { query: cohortName, context: { contextid: 1 }, includes: "self", limitfrom: 0, limitnum: 10 });
      const cohort = found.cohorts.find((entry) => entry.name === cohortName);
      expect(cohort, "the administrator must create the probe cohort").toBeTruthy();
      cohortId = cohort.id;

      await gotoOnion(page, `${base}/cohort/assign.php?id=${cohortId}`, { waitUntil: "domcontentloaded" });
      await page.locator("#addselect_searchtext").pressSequentially(suffix);
      for (const account of accounts) {
        await expect(page.locator(`#addselect option[value='${account.id}']`), `the cohort must offer ${account.username}`).toBeAttached(ACTION);
      }
      await page.locator("#addselect").selectOption(accounts.map((account) => String(account.id)), ACTION);
      await page.locator("#add").click(ACTION);
      for (const account of accounts) {
        await expect(page.locator(`#removeselect option[value='${account.id}']`), `${account.username} must join the cohort`).toBeAttached(ACTION);
      }

      const sesskey = await page.evaluate(() => window.M.cfg.sesskey);
      await gotoOnion(page, `${base}/admin/roles/admins.php?addusers=${administrator.id}&sesskey=${sesskey}`, { waitUntil: "domcontentloaded" });
      administratorId = administrator.id;
      await expect(page.locator(`#removeselect option[value='${administrator.id}']`), "the probe must become a site administrator").toBeAttached(ACTION);

      await configure(page, base, "factor_grace", { [GRACE.enabled]: true, [GRACE.forcesetup]: true }, restore);
      await configure(page, base, "factor_cohort", { [COHORT.enabled]: true, [COHORT.cohorts]: [String(cohortId)] }, restore);
      await configure(page, base, "factor_nosetup", { [NOSETUP.enabled]: false }, restore);
      await configure(page, base, "local_mfaenforce", { [FIRST_SIGN_IN.enabled]: false }, restore);

      await signIn(existing, (own) => expectDashboard(own, base, "an account without a factor, at its first sign-in before the enforcement,"));
      await signIn(existing, (own) => expectDashboard(own, base, "an existing account without a factor, before the enforcement,"));
      await signIn(administrator, (own) => expectDashboard(own, base, "a site administrator without a factor, before the enforcement,"));

      await configure(page, base, "local_mfaenforce", { [FIRST_SIGN_IN.enabled]: true }, restore);
      await signIn(fresh, (own) => expectSetupThenEnrol(own, base, "a fresh account"));
      await signIn(existing, (own) => expectSetupThenEnrol(own, base, "an existing account"));
      await signIn(administrator, (own) => expectSetupThenEnrol(own, base, "a site administrator"));

      await configure(page, base, "local_mfaenforce", { [FIRST_SIGN_IN.enabled]: false }, restore);
      await signIn(late, (own) => expectDashboard(own, base, "a fresh account without a factor, after the enforcement was switched off,"));
    } finally {
      for (const [section, previous] of restore) {
        await configure(page, base, section, previous, []).catch((error) => console.warn(`restoring ${section} failed: ${error}`));
      }
      const sesskey = await page.evaluate(() => window.M.cfg.sesskey).catch(() => "");
      if (administratorId !== null) {
        await gotoOnion(page, `${base}/admin/roles/admins.php?removeusers=${administratorId}&sesskey=${sesskey}`, { waitUntil: "domcontentloaded" })
          .catch((error) => console.warn(`removing the probe administrator failed: ${error}`));
      }
      if (cohortId !== null) {
        await ajax(page, "core_cohort_delete_cohorts", { cohortids: [cohortId] }).catch((error) => console.warn(`deleting the probe cohort failed: ${error}`));
      }
      for (const account of accounts) {
        const confirm = crypto.createHash("md5").update(String(account.id)).digest("hex");
        await gotoOnion(page, `${base}/admin/user.php?delete=${account.id}&confirm=${confirm}&sesskey=${sesskey}`, { waitUntil: "domcontentloaded" })
          .catch((error) => console.warn(`deleting ${account.username} failed: ${error}`));
      }
    }
  });
};
