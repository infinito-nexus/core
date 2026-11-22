const { test, expect } = require("@playwright/test");

const {
  decodeDotenvQuotedValue,
  gotoOnion,
  performKeycloakLoginExpectingDenial,
  requireDotenvValue,
} = require("./personas");
const { skipUnlessServiceDisabled, skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");
const {
  APP,
  LOGIN_BUTTON,
  LOGIN_USERNAME,
  READY_MS,
  SIGNED_IN,
  open,
  openSignedIn,
  ready,
  submitLogin,
} = require("./_shared");

const BIBER_USERNAME = decodeDotenvQuotedValue(requireDotenvValue(process.env.BIBER_USERNAME, "BIBER_USERNAME"));
const BIBER_PASSWORD = decodeDotenvQuotedValue(requireDotenvValue(process.env.BIBER_PASSWORD, "BIBER_PASSWORD"));
const CANONICAL_DOMAIN = requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN");
const DESCRIPTION_FIELD = 'input[name="description_0"]';
const SAVE_BUTTON = '[name="accountContainerSaveAccount"]';
const SET_PASSWORD_BUTTON = '[name="accountContainerPassword"], button:has-text("Set password")';
const NEW_PASSWORD = "input#newPassword1:visible";
const REPEAT_PASSWORD = "input#newPassword2:visible";
const PASSWORD_REPLY = "div.swal2-popup";
const PASSWORD_REPLY_OK = "button.swal2-confirm";

function exactCell(page, text) {
  const escaped = text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return page.locator("td", { hasText: new RegExp(`^\\s*${escaped}\\s*$`) });
}

async function openBiberEntry(page) {
  await openSignedIn(page, "lists/list.php?type=user", "table.accountlist tbody tr");
  const row = page.locator("table.accountlist tbody tr").filter({ has: exactCell(page, BIBER_USERNAME) }).first();
  await expect(row, `the account list must show ${BIBER_USERNAME}`).toBeVisible({ timeout: resolveTimeout(READY_MS) });
  await row.locator('a:has(img[src$="/edit.svg"])').first().click();
  await ready(page, DESCRIPTION_FIELD);
}

async function saveBiberDescription(page, value) {
  await openBiberEntry(page);
  await page.locator(DESCRIPTION_FIELD).fill(value);
  await page.locator(SAVE_BUTTON).first().click();
  await page.waitForLoadState("domcontentloaded");
  await expect(
    page.getByText("LDAP operation successful."),
    "the LAM administrator group must hold write access on other directory entries",
  ).toBeVisible({ timeout: resolveTimeout(30_000) });
}

async function acceptPasswordReply(page) {
  const reply = page.locator(PASSWORD_REPLY);
  await expect(reply, "LAM must answer the password change").toBeVisible({ timeout: resolveTimeout(30_000) });
  await expect(reply.locator("div.statusError"), "LAM must not refuse the password").toHaveCount(0);
  await expect(reply.locator("div.statusInfo").first(), "LAM must hold the password for the save").toBeVisible();
  await reply.locator(PASSWORD_REPLY_OK).click();
  await expect(reply, "the password reply must close before the account is saved").toBeHidden({
    timeout: resolveTimeout(READY_MS),
  });
}

exports.register = function () {
  test("directory login: LAM asks for a user name instead of listing administrator DNs", async ({ page }) => {
    await page.context().clearCookies();
    await open(page, "login.php", LOGIN_BUTTON);
    await expect(page.locator(LOGIN_USERNAME), "the search login renders a free user name field").toBeEditable({
      timeout: resolveTimeout(READY_MS),
    });
    await expect(page.locator("select#username"), "the fixed administrator DN list must be gone").toHaveCount(0);
  });

  test("rbac: biber without the LAM administrator role is denied at the oauth2-proxy gate", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    await page.context().clearCookies();
    await gotoOnion(page, `${APP}/lam/templates/login.php`);
    await expect
      .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "expected the oauth2-proxy redirect to Keycloak" })
      .toContain("openid-connect/auth");
    await performKeycloakLoginExpectingDenial(page, BIBER_USERNAME, BIBER_PASSWORD, CANONICAL_DOMAIN);
  });

  test("directory login: an account outside the LAM administrator group cannot sign in", async ({ page }) => {
    skipUnlessServiceDisabled("sso");
    await page.context().clearCookies();
    await submitLogin(page, BIBER_USERNAME, BIBER_PASSWORD);
    await expect(page.locator("div.statusError"), "the group filter must refuse a non-member").toBeVisible({
      timeout: resolveTimeout(30_000),
    });
    await expect(page.locator(SIGNED_IN), "a non-member must not reach the account list").toHaveCount(0);
  });

  test("directory login: the LAM administrator group edits other directory entries", async ({ page }) => {
    await page.context().clearCookies();
    await openBiberEntry(page);
    const previous = await page.locator(DESCRIPTION_FIELD).inputValue();
    const marker = `lam-acl-probe-${Date.now()}`;
    try {
      await saveBiberDescription(page, marker);
      await openBiberEntry(page);
      await expect(page.locator(DESCRIPTION_FIELD), "the saved value must persist in the directory").toHaveValue(marker);
    } finally {
      await saveBiberDescription(page, previous);
    }
  });

  test("directory login: the LAM administrator group sets the password of another account", async ({ page }) => {
    await page.context().clearCookies();
    await openBiberEntry(page);
    await page.locator(SET_PASSWORD_BUTTON).first().click();
    await expect(page.locator(NEW_PASSWORD), "LAM must open its Set password dialog").toBeEditable({
      timeout: resolveTimeout(READY_MS),
    });
    await page.locator(NEW_PASSWORD).fill(BIBER_PASSWORD);
    await page.locator(REPEAT_PASSWORD).fill(BIBER_PASSWORD);
    await page.getByRole("button", { name: /^ok$/i }).click();
    await expect(page.locator(NEW_PASSWORD), "the dialog must accept the password").toHaveCount(0, {
      timeout: resolveTimeout(30_000),
    });
    await acceptPasswordReply(page);
    await page.locator(SAVE_BUTTON).first().click();
    await page.waitForLoadState("domcontentloaded");
    await expect(
      page.getByText("LDAP operation successful."),
      "the LAM administrator group must hold write access on the userPassword of other accounts",
    ).toBeVisible({ timeout: resolveTimeout(30_000) });
  });
};
