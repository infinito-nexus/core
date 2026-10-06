const { test, expect } = require("@playwright/test");

const {
  assertDesignTokens,
  assertLightAndDark,
  assertReadable,
  assertToken,
  captureDesignGallery,
  galleryEnabled,
  tokenValue,
} = require("./design");
const {
  apiGetOnion,
  decodeDotenvQuotedValue,
  gotoOnion,
  performKeycloakLoginForm,
  safeIsEnabled,
} = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { isSplitRealmOidc, resolveTimeout } = require("./timeouts");
const {
  appBaseUrl,
  webmailBaseUrl,
  expectedOidcAuthUrl,
  adminEmail,
  adminUsername,
  adminPassword,
  stalwartAdminUsername,
  stalwartAdminPassword,
} = require("./env");
const { roundcubeSsoLogin } = require("./webmail");

const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
const lockupUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOCKUP_URL || "");
const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");

const MODES = ["light", "dark"];
const SPLIT_REALM = "clearnet app with an onion OIDC issuer: unreachable from one browser";
const WEBUI_SIGN_IN = `${appBaseUrl}/account/login`;
const WEBUI_HOME = `${appBaseUrl}/account/Account/Mailbox`;
const WEBUI_ACCOUNTS = `${appBaseUrl}/account/Management/x:Account/User`;
const WEBUI_STORE = "stalwart-ui";
const WEBUI_USERNAME = "#username";
const WEBUI_CONTINUE = "button[type='submit']";
const WEBUI_LOGO = "svg[viewBox='95 84 500 90']";
const WEBUI_THEME = "button[aria-label='Toggle theme']";
const WEBUI_USER_MENU = "button[aria-label='User menu']";
const WEBUI_HEADING = "main h1";
const WEBUI_ROW = "table tbody tr";
const WEBUI_MENU = "[role='menu']";
const WEBUI_DIALOG = "[role='dialog']";
const WEBUI_SIDEBAR = "aside";
const WEBMAIL_SIGN_IN = `${webmailBaseUrl}/?_task=login`;
const WEBMAIL_INBOX = `${webmailBaseUrl}/?_task=mail&_mbox=INBOX`;
const WEBMAIL_USER = "#rcmloginuser";
const WEBMAIL_PASSWORD = "#rcmloginpwd";
const WEBMAIL_SUBMIT = "#rcmloginsubmit";
const WEBMAIL_LOGO = "#logo";
const WEBMAIL_LIST = "#messagelist";
const WEBMAIL_FRAME = "#layout-menu";
const WEBMAIL_TASK = "#taskmenu a";
const WEBMAIL_THEME = "#taskmenu a.theme";
const WEBMAIL_PHONE_MENU = "a.task-menu-button";
const WEBMAIL_COLOR_MODE = "colorMode";
const FOCUS_WALK_LIMIT = 30;
const SHOWCASE = [
  {
    subject: "Design showcase: welcome to the corporate design",
    body: "This message was seeded for the corporate design review.\n\nIt shows how a plain text mail reads in the webmail.",
  },
  {
    subject: "Design showcase: second message of the review",
    body: "A second seeded message, so the list shows more than one entry.\n\n> A quoted line\n\nRegards,\nDesign showcase",
  },
];

/**
 * Args:
 *   page: Playwright page whose finite animations must have ended.
 */
async function animationsSettled(page) {
  await expect
    .poll(
      () =>
        page.evaluate(
          () =>
            new Promise((resolve) => {
              requestAnimationFrame(() =>
                requestAnimationFrame(() =>
                  resolve(
                    document
                      .getAnimations()
                      .some(
                        (animation) =>
                          animation.playState === "running" &&
                          animation.effect?.getComputedTiming().iterations !== Infinity,
                      ),
                  ),
                ),
              );
            }),
        ),
      { message: "every finite animation of the page must have ended" },
    )
    .toBe(false);
}

function shown(selector) {
  return async (page) => {
    await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(30_000) });
    await animationsSettled(page);
  };
}

/**
 * Args:
 *   page: Playwright page whose later documents store the web administration theme the emulated color scheme asks for, the way a first visit picks it.
 */
async function followColorScheme(page) {
  await page.addInitScript((key) => {
    if (!window.location.pathname.startsWith("/account")) return;
    const theme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    window.localStorage.setItem(key, JSON.stringify({ state: { theme }, version: 0 }));
  }, WEBUI_STORE);
}

/**
 * Args:
 *   page: Playwright page that ends signed in to the web administration, through Keycloak while sso is enabled and as the recovery administrator otherwise.
 */
async function signInWebui(page) {
  test.skip(safeIsEnabled("sso") && isSplitRealmOidc(), SPLIT_REALM);
  await gotoOnion(page, WEBUI_SIGN_IN);
  await page.locator(WEBUI_USERNAME).fill(safeIsEnabled("sso") ? adminEmail : stalwartAdminUsername);
  await page.locator(WEBUI_CONTINUE).click();
  if (safeIsEnabled("sso")) {
    await expect.poll(() => page.url(), { timeout: resolveTimeout(60_000) }).toContain(expectedOidcAuthUrl);
    await performKeycloakLoginForm(page, adminUsername, adminPassword);
  } else {
    await page.locator("#password").fill(stalwartAdminPassword);
    await page.locator("#submit-btn").click();
  }
  await expect(page.locator(WEBUI_USER_MENU)).toBeVisible({ timeout: resolveTimeout(60_000) });
}

/**
 * Args:
 *   page: Playwright page that ends signed in to the webmail as the platform administrator, through Keycloak while sso is enabled and with the mailbox password otherwise.
 */
async function signInWebmail(page) {
  test.skip(safeIsEnabled("sso") && isSplitRealmOidc(), SPLIT_REALM);
  if (safeIsEnabled("sso")) {
    await roundcubeSsoLogin(page, adminUsername, adminPassword);
  } else {
    await gotoOnion(page, WEBMAIL_SIGN_IN);
    await page.locator(WEBMAIL_USER).fill(adminEmail);
    await page.locator(WEBMAIL_PASSWORD).fill(adminPassword);
    await page.locator(WEBMAIL_SUBMIT).click();
  }
  await expect(page.locator(WEBMAIL_LIST)).toBeVisible({ timeout: resolveTimeout(60_000) });
}

/**
 * Args:
 *   request: Playwright API context that stores the showcase messages in the administrator's own inbox over JMAP when they are missing; nothing is submitted for delivery.
 */
async function seedShowcase(request) {
  const headers = { Authorization: `Basic ${Buffer.from(`${adminEmail}:${adminPassword}`).toString("base64")}` };
  const session = await request.get(`${appBaseUrl}/jmap/session`, { headers, timeout: resolveTimeout(30_000) });
  expect(session.status(), "the administrator must open a JMAP session for seeding the showcase").toBe(200);
  const accountId = (await session.json()).primaryAccounts["urn:ietf:params:jmap:mail"];
  const call = async (name, args) => {
    const response = await request.post(`${appBaseUrl}/jmap/`, {
      headers,
      data: { using: ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"], methodCalls: [[name, { accountId, ...args }, "c"]] },
      timeout: resolveTimeout(30_000),
    });
    expect(response.ok(), `the JMAP call ${name} must be accepted`).toBe(true);
    return (await response.json()).methodResponses[0][1];
  };
  const inbox = (await call("Mailbox/get", { properties: ["role"] })).list.find((entry) => entry.role === "inbox").id;
  const stored = (
    await call("Email/get", {
      ids: (await call("Email/query", { filter: { inMailbox: inbox } })).ids,
      properties: ["subject", "keywords"],
    })
  ).list;
  for (const mail of SHOWCASE) {
    const existing = stored.find((entry) => entry.subject === mail.subject);
    if (existing) {
      if (!existing.keywords.$seen) {
        const updated = await call("Email/set", { update: { [existing.id]: { "keywords/$seen": true } } });
        expect(updated.updated, `marking the showcase message '${mail.subject}' as read`).toBeTruthy();
      }
      continue;
    }
    const created = await call("Email/set", {
      create: {
        showcase: {
          mailboxIds: { [inbox]: true },
          keywords: { $seen: true },
          from: [{ name: "Design Showcase", email: adminEmail }],
          to: [{ name: "Administrator", email: adminEmail }],
          subject: mail.subject,
          bodyValues: { body: { value: mail.body } },
          textBody: [{ partId: "body", type: "text/plain" }],
        },
      },
    });
    expect(created.created, `seeding the showcase message '${mail.subject}'`).toBeTruthy();
  }
}

/**
 * Args:
 *   page: Playwright page that shows the web administration; a hidden sidebar gets opened.
 */
async function webuiSidebarOpened(page) {
  const entry = page.getByRole("button", { name: "Directory", exact: true });
  if (!(await entry.isVisible())) {
    await page.locator("header button").first().click();
    await expect(entry).toBeVisible();
  }
  await animationsSettled(page);
}

/**
 * Args:
 *   page: Playwright page that shows the webmail; on a phone layout the task menu drawer gets opened.
 */
async function webmailTaskMenuOpened(page) {
  if (await page.locator(WEBMAIL_PHONE_MENU).isVisible()) {
    await page.locator(WEBMAIL_PHONE_MENU).click();
  }
  await expect(page.locator(`${WEBMAIL_TASK}.contacts`)).toBeVisible();
  await animationsSettled(page);
}

function signedOutViews() {
  const views = [
    { name: "webui-sign-in", url: WEBUI_SIGN_IN, prepare: shown(WEBUI_USERNAME) },
    {
      name: "webui-sign-in-focus",
      url: WEBUI_SIGN_IN,
      prepare: async (page) => {
        await shown(WEBUI_USERNAME)(page);
        await page.locator(WEBUI_USERNAME).fill("administrator");
        await page.keyboard.press("Tab");
        await animationsSettled(page);
      },
    },
  ];
  if (safeIsEnabled("sso")) return views;
  return [
    ...views,
    {
      name: "webui-sign-in-password",
      url: WEBUI_SIGN_IN,
      prepare: async (page) => {
        await shown(WEBUI_USERNAME)(page);
        await page.locator(WEBUI_USERNAME).fill(stalwartAdminUsername);
        await page.locator(WEBUI_CONTINUE).click();
        await shown("#password")(page);
      },
    },
    { name: "webmail-sign-in", url: WEBMAIL_SIGN_IN, prepare: shown(WEBMAIL_SUBMIT) },
    {
      name: "webmail-sign-in-focus",
      url: WEBMAIL_SIGN_IN,
      prepare: async (page) => {
        await shown(WEBMAIL_SUBMIT)(page);
        await page.locator(WEBMAIL_USER).fill(adminEmail);
        await page.keyboard.press("Tab");
        await animationsSettled(page);
      },
    },
  ];
}

function webuiViews() {
  const view = (name, path, selector) => ({ name, url: `${appBaseUrl}/account/${path}`, prepare: shown(selector) });
  return [
    view("webui-accounts", "Management/x:Account/User", WEBUI_ROW),
    {
      name: "webui-account-create",
      url: WEBUI_ACCOUNTS,
      prepare: async (page) => {
        await shown(WEBUI_ROW)(page);
        await page.getByRole("button", { name: "Create user" }).click();
        await shown("main form input, main input[type='text']")(page);
      },
    },
    {
      name: "webui-account-menu",
      url: WEBUI_ACCOUNTS,
      prepare: async (page) => {
        await shown(WEBUI_ROW)(page);
        await page.locator(`${WEBUI_ROW} button[aria-haspopup='menu']`).first().click();
        await shown(WEBUI_MENU)(page);
        await expect(page.locator(WEBUI_MENU).first()).toHaveCSS("opacity", "1");
      },
    },
    view("webui-dkim", "Management/x:DkimSignature", WEBUI_ROW),
    view("webui-settings-network", "Settings/x:SystemSettings/NetworkSettings", "main input"),
    view("webui-settings-authentication", "Settings/x:Authentication", WEBUI_HEADING),
    view("webui-mailboxes", "Account/Mailbox", WEBUI_HEADING),
    {
      name: "webui-user-menu",
      url: WEBUI_ACCOUNTS,
      prepare: async (page) => {
        await shown(WEBUI_ROW)(page);
        await page.locator(WEBUI_USER_MENU).click();
        await shown(WEBUI_MENU)(page);
        await expect(page.locator(WEBUI_MENU).first()).toHaveCSS("opacity", "1");
      },
    },
    {
      name: "webui-enterprise-dialog",
      url: WEBUI_ACCOUNTS,
      prepare: async (page) => {
        await shown(WEBUI_ROW)(page);
        await page.locator(WEBUI_USER_MENU).click();
        await page.getByRole("menuitem", { name: "Try Enterprise" }).click();
        await shown(WEBUI_DIALOG)(page);
        await expect(page.locator(WEBUI_DIALOG).first()).toHaveCSS("opacity", "1");
      },
    },
    {
      name: "webui-navigation",
      url: WEBUI_ACCOUNTS,
      prepare: async (page) => {
        await shown(WEBUI_ROW)(page);
        await webuiSidebarOpened(page);
        await page.getByRole("button", { name: "Domains", exact: true }).click();
        await page.getByRole("button", { name: "DKIM Signatures", exact: true }).hover();
        await animationsSettled(page);
      },
    },
  ];
}

function webmailViews() {
  const view = (name, query, selector) => ({ name, url: `${webmailBaseUrl}/?${query}`, prepare: shown(selector) });
  const framed = (name, query, row, frame, content) => ({
    name,
    url: `${webmailBaseUrl}/?${query}`,
    prepare: async (page) => {
      await shown(row)(page);
      await page.locator(row).first().click();
      await expect(page.frameLocator(frame).locator(content).first()).toBeVisible({ timeout: resolveTimeout(60_000) });
      await animationsSettled(page);
    },
  });
  return [
    view("webmail-inbox", "_task=mail&_mbox=INBOX", `${WEBMAIL_LIST} tr.message`),
    {
      name: "webmail-message",
      url: WEBMAIL_INBOX,
      prepare: async (page) => {
        await shown(`${WEBMAIL_LIST} tr.message`)(page);
        const link = page.locator(`${WEBMAIL_LIST} tr.message`, { hasText: SHOWCASE[0].subject }).first().locator("a[href*='_uid=']");
        const uid = /_uid=(\d+)/.exec(await link.first().getAttribute("href"))[1];
        await gotoOnion(page, `${WEBMAIL_INBOX}&_uid=${uid}&_action=show`);
        await shown("#messagebody")(page);
      },
    },
    {
      name: "webmail-list-menu",
      url: WEBMAIL_INBOX,
      prepare: async (page) => {
        await shown(`${WEBMAIL_LIST} tr.message`)(page);
        await page.locator("#layout-list .header a.toolbar-menu-button:visible, #toolbar-list-menu a.select:visible").first().click();
        await shown(".popover.show")(page);
        await expect(page.locator(".popover.show").first()).toHaveCSS("opacity", "1");
      },
    },
    view("webmail-compose", "_task=mail&_action=compose", "#compose-subject"),
    view("webmail-contacts", "_task=addressbook", "#directorylist li:visible, #layout-list .header:visible"),
    framed("webmail-preferences", "_task=settings&_action=preferences", "#sections-table tr", "#preferences-frame", "form"),
    view("webmail-folders", "_task=settings&_action=folders", "#subscription-table li:visible"),
    framed("webmail-identities", "_task=settings&_action=identities", "#identities-table tr", "#preferences-frame", "form"),
    {
      name: "webmail-navigation-focus",
      url: WEBMAIL_INBOX,
      prepare: async (page) => {
        await shown(`${WEBMAIL_LIST} tr.message`)(page);
        await webmailTaskMenuOpened(page);
        await page.locator(`${WEBMAIL_TASK}.mail`).focus();
        await page.keyboard.press("Tab");
        await animationsSettled(page);
      },
    },
  ];
}

/**
 * Args:
 *   page: Playwright page that shows the element.
 *   selector: element whose computed style is read.
 *   property: CSS property to read.
 *
 * Returns:
 *   The computed value of the property on the first match.
 */
async function computed(page, selector, property) {
  return page
    .locator(selector)
    .first()
    .evaluate((element, name) => getComputedStyle(element).getPropertyValue(name), property);
}

/**
 * Args:
 *   page: Playwright page that can load the image.
 *   url: image URL the content security policy of the page must allow.
 */
async function assertLoads(page, url) {
  expect(
    await page.evaluate(
      (src) =>
        new Promise((resolve) => {
          const image = new Image();
          image.onload = () => resolve(image.naturalWidth > 0);
          image.onerror = () => resolve(false);
          image.src = src;
        }),
      url,
    ),
    `the page must be allowed to load ${url}`,
  ).toBe(true);
}

/**
 * Args:
 *   page: Playwright page whose focused element is inspected.
 *
 * Returns:
 *   The name of the focused element, whether the webmail task menu holds it, and the color and style of its outline.
 */
async function focusStop(page) {
  return page.evaluate((frame) => {
    const element = document.activeElement;
    const style = getComputedStyle(element);
    return {
      name: [element.tagName.toLowerCase(), ...element.classList].join("."),
      framed: Boolean(element.closest(frame)),
      outline: style.outlineStyle === "none" || parseFloat(style.outlineWidth) === 0 ? "" : style.outlineColor,
    };
  }, WEBMAIL_FRAME);
}

/**
 * Args:
 *   page: Playwright page that shows the webmail; the keyboard walks from the first entry of the task menu through every stop it holds.
 *   mode: color scheme the failure messages name.
 */
async function assertFrameFocus(page, mode) {
  const ring = await tokenValue(page, "--design-on-frame", "color");
  const stops = [];
  await page.locator(WEBMAIL_TASK).first().focus();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Shift+Tab");
  for (let step = 0; step < FOCUS_WALK_LIMIT; step += 1) {
    const stop = await focusStop(page);
    if (!stop.framed) break;
    stops.push(stop.name);
    await expect
      .poll(async () => (await focusStop(page)).outline, {
        message: `keyboard stop ${stop.name} of the task menu ${mode}: the focus outline must be drawn in --design-on-frame`,
      })
      .toBe(ring);
    await page.keyboard.press("Tab");
  }
  expect(stops.length, `the keyboard walk must find stops inside the task menu ${mode}`).toBeGreaterThan(1);
}

test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await gotoOnion(page, WEBUI_SIGN_IN);
  await shown(WEBUI_USERNAME)(page);
  await assertDesignTokens(page, "stalwart web administration");
});

test("design: the web administration sign-in takes surface, primary action and text from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, WEBUI_SIGN_IN);
    await shown(WEBUI_USERNAME)(page);
    await assertToken(page, "body", "background-color", "--design-surface-2", `sign-in ${mode}`);
    await assertToken(page, WEBUI_USERNAME, "color", "--design-text", `sign-in ${mode}`);
    await assertToken(page, WEBUI_USERNAME, "border-top-color", "--design-border-strong", `sign-in ${mode}`);
    await page.locator(WEBUI_USERNAME).fill("administrator");
    await assertToken(page, WEBUI_CONTINUE, "background-color", "--design-primary", `sign-in ${mode}`);
    await assertToken(page, WEBUI_CONTINUE, "color", "--design-on-primary", `sign-in ${mode}`);
    await page.locator(WEBUI_CONTINUE).hover();
    await assertToken(page, WEBUI_CONTINUE, "background-color", "--design-primary-hover", `hovered sign-in ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await gotoOnion(page, WEBUI_SIGN_IN);
  await shown(WEBUI_USERNAME)(page);
  await page.locator(WEBUI_USERNAME).fill("administrator");
  await assertLightAndDark(page, WEBUI_USERNAME, "stalwart sign-in");
  await assertReadable(page, [WEBUI_USERNAME, WEBUI_CONTINUE, { selector: "form p", optional: true }], "stalwart sign-in");
});

test("design: the signed-in web administration takes surfaces and text from the palette in both themes", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await followColorScheme(page);
  await signInWebui(page);
  const selected = `${WEBUI_SIDEBAR} button:has-text("Mailboxes")`;
  const unselected = `${WEBUI_SIDEBAR} button:has-text("Calendars")`;
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, WEBUI_HOME);
    await shown(WEBUI_HEADING)(page);
    await expect(page.locator("html")).toHaveAttribute("data-design-theme", mode);
    await assertToken(page, "header", "background-color", "--design-surface-2", `shell ${mode}`);
    await assertToken(page, WEBUI_SIDEBAR, "background-color", "--design-surface-2", `shell ${mode}`);
    await assertToken(page, "main", "background-color", "--design-surface-1", `shell ${mode}`);
    await assertToken(page, WEBUI_HEADING, "color", "--design-text", `shell ${mode}`);
    await assertToken(page, unselected, "color", "--design-text", `shell ${mode}`);
    expect(
      await computed(page, selected, "background-color"),
      `the selected sidebar entry must stand out from an unselected one ${mode}`,
    ).not.toBe(await computed(page, unselected, "background-color"));
    await page.locator(unselected).hover();
    await assertToken(page, unselected, "background-color", "--design-surface-hover", `hovered sidebar entry ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
});

test("design: the theme toggle of the web administration is respected and mirrored", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.emulateMedia({ colorScheme: "light" });
  await signInWebui(page);
  await gotoOnion(page, WEBUI_HOME);
  await shown(WEBUI_HEADING)(page);
  const html = page.locator("html");
  const surface = () => tokenValue(page, "--design-surface-1", "background-color");
  const lightSurface = await surface();

  await page.locator(WEBUI_THEME).click();
  await expect(html).toHaveClass(/\bdark\b/);
  await expect(html).toHaveAttribute("data-design-theme", "dark");
  expect(await surface(), "the dark theme of the web administration must switch the tokens while the browser prefers light").not.toBe(
    lightSurface,
  );
  await assertToken(page, "main", "background-color", "--design-surface-1", "dark theme picked in the web administration");

  await gotoOnion(page, page.url());
  await shown(WEBUI_HEADING)(page);
  await expect(html, "the picked theme must survive a reload").toHaveAttribute("data-design-theme", "dark");

  await page.emulateMedia({ colorScheme: "dark" });
  await page.locator(WEBUI_THEME).click();
  await expect(html).not.toHaveClass(/\bdark\b/);
  await expect(html).toHaveAttribute("data-design-theme", "light");
  expect(await surface(), "the light theme of the web administration must keep the light tokens while the browser prefers dark").toBe(
    lightSurface,
  );
  await page.emulateMedia({ colorScheme: null });
});

test("design: the web administration shows the generated lockup and the configured title", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");
  await page.setViewportSize({ width: 1440, height: 900 });
  await gotoOnion(page, WEBUI_SIGN_IN);
  await shown(WEBUI_USERNAME)(page);
  if (title) await expect(page).toHaveTitle(title);
  if (logoUrl) {
    expect(faviconUrl, "a role that renders a logo also renders DESIGN_FAVICON_URL").toBeTruthy();
    const logo = page.locator(WEBUI_LOGO);
    await expect(logo).toHaveCSS("background-image", `url("${lockupUrl || logoUrl}")`);
    await expect(logo.locator("path").first()).toHaveCSS("visibility", "hidden");
    await expect(page.locator("link[rel~='icon']")).toHaveAttribute("href", faviconUrl);
    for (const url of [lockupUrl || logoUrl, faviconUrl]) await assertLoads(page, url);
    if (lockupUrl) {
      const box = await logo.boundingBox();
      expect(box.width, `the logo box is ${box.width}x${box.height} and must be at least twice as wide as high`).toBeGreaterThanOrEqual(
        2 * box.height,
      );
      const lockup = await apiGetOnion(page.request, lockupUrl);
      expect(lockup.ok(), "the lockup must be served").toBe(true);
      const source = await lockup.text();
      const natural = { width: Number(/width="(\d+)"/.exec(source)[1]), height: Number(/height="(\d+)"/.exec(source)[1]) };
      const painted = 1.25 * box.height;
      expect((painted * natural.width) / natural.height, "the lockup must fit the width of its box").toBeLessThanOrEqual(box.width);
      const titleSize = (Number(/font-size="(\d+)"/.exec(source)[1]) * painted) / natural.height;
      expect(titleSize, "the title of the lockup must not be smaller than the interface text").toBeGreaterThanOrEqual(
        parseFloat(await computed(page, WEBUI_USERNAME, "font-size")),
      );
    }
  }
});

test("design: the webmail takes frame, surfaces, primary action and text from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.setViewportSize({ width: 1440, height: 900 });
  await signInWebmail(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, WEBMAIL_INBOX);
    await shown(WEBMAIL_LIST)(page);
    await expect(page.locator("html")).toHaveClass(mode === "dark" ? /dark-mode/ : /^(?!.*dark-mode)/);
    await assertToken(page, WEBMAIL_FRAME, "background-color", "--design-frame", `frame ${mode}`);
    await assertToken(page, `${WEBMAIL_TASK}.contacts`, "color", "--design-on-frame", `frame ${mode}`);
    await assertToken(page, `${WEBMAIL_TASK}.compose`, "color", "--design-on-frame", `frame ${mode}`);
    await assertToken(page, `${WEBMAIL_TASK}.logout`, "color", "--design-on-frame", `frame ${mode}`);
    await assertToken(page, `${WEBMAIL_TASK}.selected`, "background-color", "--design-frame-active", `selected task ${mode}`);
    await assertToken(page, "body", "background-color", "--design-surface-2", `shell ${mode}`);
    await assertToken(page, "body", "color", "--design-text", `shell ${mode}`);
    await assertToken(page, "#mailboxlist li.selected > a", "background-color", "--design-surface-active", `selected folder ${mode}`);
    await page.locator(`${WEBMAIL_TASK}.contacts`).hover();
    await assertToken(page, `${WEBMAIL_TASK}.contacts`, "background-color", "--design-frame-hover", `hovered task ${mode}`);
    await gotoOnion(page, WEBMAIL_INBOX);
    await shown(WEBMAIL_LIST)(page);
    await assertFrameFocus(page, mode);
    await gotoOnion(page, `${webmailBaseUrl}/?_task=mail&_action=compose`);
    await shown("#compose-subject")(page);
    await assertToken(page, "button.btn-primary", "background-color", "--design-primary", `primary action ${mode}`);
    await assertToken(page, "button.btn-primary", "color", "--design-on-primary", `primary action ${mode}`);
    await assertToken(page, "#compose-subject", "border-top-color", "--design-border-strong", `form field ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await gotoOnion(page, WEBMAIL_INBOX);
  await shown(WEBMAIL_LIST)(page);
  await assertLightAndDark(page, "#layout-list", "webmail");
  await assertReadable(
    page,
    ["#mailboxlist li.mailbox a", `${WEBMAIL_TASK}.contacts`, `${WEBMAIL_TASK}.selected`, "#layout-sidebar .header", "#toolbar-list-menu a.options"],
    "webmail",
  );
});

test("design: the empty content frame and the phone task menu of the webmail keep the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signInWebmail(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await page.setViewportSize({ width: 1440, height: 900 });
    await gotoOnion(page, WEBMAIL_INBOX);
    await shown(WEBMAIL_LIST)(page);
    const surface = await tokenValue(page, "--design-surface-2", "background-color");
    await expect
      .poll(
        () =>
          page
            .frameLocator("#messagecontframe")
            .locator("body")
            .evaluate((body) => getComputedStyle(body).backgroundColor),
        { message: `the empty content frame must take --design-surface-2 ${mode}` },
      )
      .toBe(surface);

    await page.setViewportSize({ width: 390, height: 844 });
    await gotoOnion(page, WEBMAIL_INBOX);
    await shown(WEBMAIL_LIST)(page);
    await webmailTaskMenuOpened(page);
    await assertToken(page, WEBMAIL_FRAME, "background-color", "--design-surface-2", `phone task menu ${mode}`);
    await assertToken(page, `${WEBMAIL_TASK}.compose`, "color", "--design-link", `phone task menu ${mode}`);
    await assertToken(page, `${WEBMAIL_TASK}.contacts`, "color", "--design-text", `phone task menu ${mode}`);
    await assertToken(page, `${WEBMAIL_TASK}.logout`, "background-color", "--design-surface-2", `phone task menu ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
});

test("design: the dark mode switch of the webmail is respected and mirrored", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ colorScheme: "light" });
  await signInWebmail(page);
  const html = page.locator("html");
  const surface = () => tokenValue(page, "--design-surface-2", "background-color");
  const lightSurface = await surface();
  await expect(html, "the palette follows the browser preference").not.toHaveAttribute("data-design-theme");

  await page.locator(WEBMAIL_THEME).click();
  await expect(html).toHaveClass(/dark-mode/);
  await expect(html).toHaveAttribute("data-design-theme", "dark");
  expect(await surface(), "the dark mode of the webmail must switch the tokens while the browser prefers light").not.toBe(lightSurface);
  await assertToken(page, "body", "background-color", "--design-surface-2", "dark mode picked in the webmail");

  await gotoOnion(page, page.url());
  await shown(WEBMAIL_LIST)(page);
  await expect(html, "the picked mode must survive a reload").toHaveAttribute("data-design-theme", "dark");

  await page.locator(WEBMAIL_THEME).click();
  await expect(html).not.toHaveClass(/dark-mode/);
  expect(await surface(), "the light mode of the webmail must bring the light tokens back").toBe(lightSurface);
  await page.context().clearCookies({ name: WEBMAIL_COLOR_MODE });
});

test("design: the webmail shows the generated logo and the configured title", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");
  await page.setViewportSize({ width: 1440, height: 900 });
  await signInWebmail(page);
  if (title) await expect(page).toHaveTitle(new RegExp(title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  if (logoUrl) {
    await expect(page.locator(WEBMAIL_LOGO)).toHaveAttribute("src", logoUrl);
    await expect(page.locator("link[rel~='icon']").first()).toHaveAttribute("href", faviconUrl);
    for (const url of [logoUrl, faviconUrl]) await assertLoads(page, url);
    const box = await page.locator(WEBMAIL_LOGO).boundingBox();
    expect(Math.abs(box.width - box.height), "the task menu gives the logo a square box").toBeLessThanOrEqual(2);
  }
});

test("design: gallery of sign-in, administration, settings, webmail, dialogs and menus", async ({ page, request }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
  test.setTimeout(resolveTimeout(2_400_000));
  await followColorScheme(page);

  const failures = [];
  const capture = async (views) => {
    try {
      await captureDesignGallery(page, views);
    } catch (error) {
      failures.push(error.message);
    }
  };
  await capture(signedOutViews());
  if (!safeIsEnabled("sso")) await seedShowcase(request);
  await signInWebui(page);
  await signInWebmail(page);
  await capture([...webuiViews(), ...webmailViews()]);
  expect(failures, failures.join("\n")).toEqual([]);
});
