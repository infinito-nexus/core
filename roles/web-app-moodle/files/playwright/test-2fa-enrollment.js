const crypto = require("crypto");
const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceDisabled } = require("./service-gating");
const { gotoOnion, recordVideoOptions, requireDotenvValue } = require("./personas");

const ACTION = { timeout: resolveTimeout(30_000) };
const SETTINGS_SAVE = "form#adminsettings button[type='submit']";
const SETTINGS_SAVED = ".alert-success";
const SETUP_PAGE = /\/admin\/tool\/mfa\/user_preferences\.php/;
const COHORT = {
  enabled: "#id_s_factor_cohort_enabled",
  cohorts: "#id_s_factor_cohort_cohorts",
};
const GRACE = {
  enabled: "#id_s_factor_grace_enabled",
  forcesetup: "#id_s_factor_grace_forcesetup",
  period: "#id_s_factor_grace_graceperiodv",
  unit: "#id_s_factor_grace_graceperiodu",
};
const NOSETUP = { enabled: "#id_s_factor_nosetup_enabled" };

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
 * @param {string} section admin settings section of one factor
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
 * @param {import('@playwright/test').Browser} browser browser that opens a fresh context
 * @param {import('@playwright/test').TestInfo} testInfo running test, for its proxy and video settings
 * @returns {Promise<{context: import('@playwright/test').BrowserContext, page: import('@playwright/test').Page}>} the context and its page
 */
async function freshSession(browser, testInfo) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true, proxy: testInfo.project.use.proxy, ...recordVideoOptions(testInfo) });
  return { context, page: await context.newPage() };
}

exports.register = function (shared) {
  test("2fa enrollment: with its own second factor enforced Moodle sends a local account without one to setup before it gets in", async ({ browser, page }, testInfo) => {
    skipUnlessServiceDisabled("sso");
    test.skip(!twoFactorEnabled(), "LOGIN_METHOD_2FA_ENABLED=false");
    test.setTimeout(resolveTimeout(420_000));

    const base = shared.env.moodleBaseUrl;
    const suffix = `${Date.now().toString(36)}${crypto.randomBytes(3).toString("hex")}`;
    const probe = {
      username: `infinito-2fa-probe-${suffix}`,
      password: `${crypto.randomBytes(24).toString("base64url")}Aa1-`,
      cohort: `Infinito 2FA probe ${suffix}`,
    };

    await shared.loginAsSiteAdmin(page);
    let probeId = null;
    let cohortId = null;
    const restore = [];
    let session = null;
    try {
      await gotoOnion(page, `${base}/user/editadvanced.php?id=-1`, { waitUntil: "domcontentloaded" });
      await expect(page.locator("#id_username"), "the new user form must render").toBeEditable(ACTION);
      await page.locator("#id_username").fill(probe.username);
      const unmask = page.locator("[data-passwordunmaskid='id_newpassword'] [data-passwordunmask='edit']");
      if (await unmask.isVisible()) {
        await unmask.click(ACTION);
      }
      await page.locator("#id_newpassword").fill(probe.password, ACTION);
      await page.locator("#id_firstname").fill("Infinito");
      await page.locator("#id_lastname").fill(`2FA probe ${suffix}`);
      await page.locator("#id_email").fill(`${probe.username}@${requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN")}`);
      await page.locator("#id_submitbutton").click(ACTION);
      await page.waitForURL((url) => !url.pathname.endsWith("/user/editadvanced.php"), ACTION);
      const users = await ajax(page, "core_user_get_users_by_field", { field: "username", values: [probe.username] });
      expect(users.length, "the administrator must create the probe account").toBe(1);
      probeId = users[0].id;

      await configure(page, base, "factor_grace", {
        [GRACE.enabled]: true,
        [GRACE.forcesetup]: true,
        [GRACE.period]: "1",
        [GRACE.unit]: "1",
      }, restore);

      session = await freshSession(browser, testInfo);
      await shared.loginAsDirectoryUser(session.page, probe.username, probe.password);
      await session.context.close();
      session = null;

      await gotoOnion(page, `${base}/cohort/edit.php?contextid=1`, { waitUntil: "domcontentloaded" });
      await expect(page.locator("#id_name"), "the new cohort form must render").toBeEditable(ACTION);
      await page.locator("#id_name").fill(probe.cohort);
      await page.locator("#id_submitbutton").click(ACTION);
      await page.waitForURL((url) => !url.pathname.endsWith("/cohort/edit.php"), ACTION);
      const found = await ajax(page, "core_cohort_search_cohorts", { query: probe.cohort, context: { contextid: 1 }, includes: "self", limitfrom: 0, limitnum: 10 });
      const cohort = found.cohorts.find((entry) => entry.name === probe.cohort);
      expect(cohort, "the administrator must create the probe cohort").toBeTruthy();
      cohortId = cohort.id;

      await gotoOnion(page, `${base}/cohort/assign.php?id=${cohortId}`, { waitUntil: "domcontentloaded" });
      await page.locator("#addselect_searchtext").pressSequentially(suffix);
      await expect(page.locator(`#addselect option[value='${probeId}']`), "the cohort must offer the probe account").toBeAttached(ACTION);
      await page.locator("#addselect").selectOption(String(probeId), ACTION);
      await page.locator("#add").click(ACTION);
      await expect(page.locator(`#removeselect option[value='${probeId}']`), "the probe account must join the cohort").toBeAttached(ACTION);

      await configure(page, base, "factor_cohort", { [COHORT.enabled]: true, [COHORT.cohorts]: [String(cohortId)] }, restore);
      await configure(page, base, "factor_nosetup", { [NOSETUP.enabled]: false }, restore);

      session = await freshSession(browser, testInfo);
      await session.page.waitForTimeout(resolveTimeout(2_000));
      await shared.submitLoginForm(session.page, probe.username, probe.password);
      await expect(session.page, "an account without a factor must land on the MFA setup once its grace is over").toHaveURL(SETUP_PAGE, {
        timeout: resolveTimeout(60_000),
      });
      await expect(
        session.page.getByText(/you must complete setup for multi-factor authentication before you can proceed/i).first(),
        "the setup page must say that the setup is required",
      ).toBeVisible(ACTION);
      await expect(
        session.page.getByRole("button", { name: /set up authenticator app/i }).or(session.page.getByRole("link", { name: /set up authenticator app/i })).first(),
        "the setup page must offer the authenticator app",
      ).toBeVisible(ACTION);

      await gotoOnion(session.page, `${base}/my/`, { waitUntil: "domcontentloaded" });
      await expect(session.page, "the dashboard must hand the account back to the MFA setup").toHaveURL(SETUP_PAGE, {
        timeout: resolveTimeout(60_000),
      });
    } finally {
      await (session ? session.context.close() : Promise.resolve()).catch(() => {});
      for (const [section, previous] of restore) {
        await configure(page, base, section, previous, []).catch((error) => console.warn(`restoring ${section} failed: ${error}`));
      }
      if (cohortId !== null) {
        await ajax(page, "core_cohort_delete_cohorts", { cohortids: [cohortId] }).catch((error) => console.warn(`deleting the probe cohort failed: ${error}`));
      }
      if (probeId !== null) {
        const sesskey = await page.evaluate(() => window.M.cfg.sesskey).catch(() => "");
        const confirm = crypto.createHash("md5").update(String(probeId)).digest("hex");
        await gotoOnion(page, `${base}/admin/user.php?delete=${probeId}&confirm=${confirm}&sesskey=${sesskey}`, { waitUntil: "domcontentloaded" })
          .catch((error) => console.warn(`deleting the probe account failed: ${error}`));
      }
    }
  });
};
