const crypto = require("crypto");
const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceDisabled } = require("./service-gating");
const { gotoOnion, normalizeBaseUrl, recordVideoOptions, requireDotenvValue } = require("./personas");
const { signInToAdministrator, submitSiteLogin } = require("./joomla-session");

const base = normalizeBaseUrl(requireDotenvValue(process.env.JOOMLA_BASE_URL, "JOOMLA_BASE_URL"));
const canonicalDomain = requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN");
const adminUsername = requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME");
const adminPassword = requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD");
const twoFactorEnabled = process.env.LOGIN_METHOD_2FA_ENABLED === "true";

const ACTION = { timeout: resolveTimeout(30_000) };
const REGISTERED_GROUP = "2";
const ADMIN_ROW = "form#adminForm table tbody tr";
const ENFORCED_GROUPS = "select#jform_forceMFAUserGroups";
const COM_USERS_OPTIONS = "option=com_config&view=component&component=com_users";
const SAVED = "#system-message-container joomla-alert[type='success']";
const METHODS = /[?&]view=methods\b|\/users\/methods\b/;

test.use({ ignoreHTTPSErrors: true });

const admin = (query) => `${base}/administrator/index.php?${query}`;

/**
 * Args:
 *   page: Playwright page with an administrator session on an edit form.
 *   task: the Joomla apply task that saves the form and reopens it.
 *
 * Returns:
 *   The id of the saved record, read from the reopened form's URL.
 */
async function applyAndReadId(page, task) {
  await page.evaluate((apply) => window.Joomla.submitbutton(apply), task);
  await expect(page, `${task} must reopen the saved record`).toHaveURL(/[?&]id=[1-9]\d*/, ACTION);
  return new URL(page.url()).searchParams.get("id");
}

/**
 * Args:
 *   page: Playwright page with an administrator session.
 *
 * Returns:
 *   The group ids the com_users option forceMFAUserGroups holds, read from a freshly loaded options form.
 */
async function enforcedGroups(page) {
  await gotoOnion(page, admin(COM_USERS_OPTIONS));
  await expect(page.locator(ENFORCED_GROUPS), "the com_users options must carry Enforce Multi-factor Authentication").toBeAttached(ACTION);
  return page.locator(ENFORCED_GROUPS).evaluate((select) => Array.from(select.selectedOptions, (option) => option.value));
}

/**
 * Args:
 *   page: Playwright page with an administrator session.
 *   groups: the group ids forceMFAUserGroups must hold afterwards.
 */
async function enforceGroups(page, groups) {
  await enforcedGroups(page);
  await page.locator(ENFORCED_GROUPS).evaluate((select, wanted) => {
    const choices = select.closest("joomla-field-fancy-select")?.choicesInstance;
    if (choices) {
      choices.removeActiveItems();
      choices.setChoiceByValue(wanted);
    } else {
      Array.from(select.options).forEach((option) => {
        option.selected = wanted.includes(option.value);
      });
    }
  }, groups);
  await page.evaluate(() => window.Joomla.submitbutton("component.apply"));
  await expect(page.locator(SAVED), "the com_users options must save").toBeVisible(ACTION);
  expect((await enforcedGroups(page)).sort(), "the saved com_users options must hold exactly the wanted enforced groups").toEqual([...groups].sort());
}

/**
 * Args:
 *   page: Playwright page with an administrator session.
 *   view: com_users list view that holds the entry, users or groups.
 *   name: the entry's username or group title.
 *   task: the list task that deletes it.
 */
async function deleteEntry(page, view, name, task) {
  const list = admin(`option=com_users&view=${view}&filter[search]=${encodeURIComponent(name)}`);
  const row = page.locator(ADMIN_ROW).filter({ hasText: name });
  await gotoOnion(page, list);
  await row.first().locator("input[name='cid[]']").check(ACTION);
  await page.evaluate((remove) => window.Joomla.submitbutton(remove), task);
  await expect(page.locator(SAVED), `${task} must report success`).toBeVisible(ACTION);
  await gotoOnion(page, list);
  await expect(row, `${task} must remove ${name}`).toHaveCount(0, ACTION);
}

test("2fa enrollment: with its own second factor enforced Joomla sends a local account without one to setup before it gets in", async ({ browser, page }, testInfo) => {
  skipUnlessServiceDisabled("sso");
  test.skip(!twoFactorEnabled, "LOGIN_METHOD_2FA_ENABLED=false");
  test.setTimeout(resolveTimeout(300_000));

  const suffix = `${Date.now().toString(36)}${crypto.randomBytes(3).toString("hex")}`;
  const probe = {
    username: `infinito-2fa-probe-${suffix}`,
    password: `${crypto.randomBytes(24).toString("base64url")}Aa1-`,
    group: `Infinito 2FA probe ${suffix}`,
  };

  await signInToAdministrator(page, base, adminUsername, adminPassword);
  let groupId = null;
  let userCreated = false;
  let previous = null;
  let probeContext = null;
  try {
    await gotoOnion(page, admin("option=com_users&task=group.add"));
    await expect(page.locator("#jform_title"), "the new group form must render").toBeEditable(ACTION);
    await page.locator("#jform_title").fill(probe.group);
    await page.locator("#jform_parent_id").selectOption(REGISTERED_GROUP);
    groupId = await applyAndReadId(page, "group.apply");

    await gotoOnion(page, admin("option=com_users&task=user.add"));
    await expect(page.locator("#jform_name"), "the new user form must render").toBeEditable(ACTION);
    await page.locator("#jform_name").fill("Infinito 2FA probe");
    await page.locator("#jform_username").fill(probe.username);
    await page.locator("#jform_password").fill(probe.password);
    await page.locator("#jform_password2").fill(probe.password);
    await page.locator("#jform_email").fill(`${probe.username}@${canonicalDomain}`);
    await page.locator(`input[name='jform[groups][]'][value='${groupId}']`).evaluate((box) => {
      box.checked = true;
    });
    await applyAndReadId(page, "user.apply");
    userCreated = true;

    previous = await enforcedGroups(page);
    expect(previous, "a fresh group cannot be enforced yet").not.toContain(groupId);
    await enforceGroups(page, [...previous, groupId]);

    probeContext = await browser.newContext({ ignoreHTTPSErrors: true, proxy: testInfo.project.use.proxy, ...recordVideoOptions(testInfo) });
    const probePage = await probeContext.newPage();
    await submitSiteLogin(probePage, base, probe.username, probe.password);
    await expect(probePage, "a member of an enforced group without a factor must land on the MFA methods page").toHaveURL(METHODS, {
      timeout: resolveTimeout(60_000),
    });
    await expect(
      probePage.locator(".alert-info .alert-heading").filter({ hasText: /multi-factor authentication is mandatory for your user account/i }),
      "the methods page must say that a second factor is mandatory",
    ).toBeVisible(ACTION);
    await expect(probePage.locator("#com-users-methods-list"), "the methods page must list the methods to set up").toBeVisible(ACTION);
    await expect(probePage.locator("a.com-users-methods-list-method-addnew").first(), "the methods page must offer to add a factor").toBeVisible(ACTION);

    await gotoOnion(probePage, `${base}/index.php?option=com_users&view=profile`);
    await expect(probePage, "the site must hand the account back to the MFA methods page").toHaveURL(METHODS, {
      timeout: resolveTimeout(60_000),
    });
    await expect(probePage.locator("main .com-users-profile"), "the profile must stay out of reach").toHaveCount(0);
  } finally {
    await (probeContext ? probeContext.close() : Promise.resolve()).catch(() => {});
    if (previous !== null) {
      await enforceGroups(page, previous).catch((error) => console.warn(`restoring forceMFAUserGroups failed: ${error}`));
    }
    if (userCreated) {
      await deleteEntry(page, "users", probe.username, "users.delete").catch((error) => console.warn(`deleting the probe account failed: ${error}`));
    }
    if (groupId !== null) {
      await deleteEntry(page, "groups", probe.group, "groups.delete").catch((error) => console.warn(`deleting the probe group failed: ${error}`));
    }
  }
});
