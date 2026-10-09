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
const { decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const base = normalizeBaseUrl(requireDotenvValue(process.env.OPENBAO_BASE_URL, "OPENBAO_BASE_URL"));
const kvMount = requireDotenvValue(process.env.OPENBAO_KV_MOUNT, "OPENBAO_KV_MOUNT");
const adminUsername = requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME");
const adminPassword = requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD");
const passwordMount = decodeDotenvQuotedValue(process.env.OPENBAO_PASSWORD_AUTH_MOUNT || "");
const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");

const MODES = ["light", "dark"];
const NO_PASSWORD_SIGN_IN =
  "neither LDAP nor the userpass fallback carries a password sign-in (OPENBAO_PASSWORD_AUTH_MOUNT is empty); test-oidc-login.js asserts the OIDC round-trip";
const SIGN_IN_FORM = "#auth-form";
const SIGN_IN_BOX = ".login-form";
const SUBMIT = "#auth-submit";
const MORE_OPTIONS = `${SIGN_IN_FORM} button.is-transparent`;
const BRAND = ".brand-icon-large";
const SIDE_NAV = ".hds-side-nav";
const HOSTED_POPUP = `${SIDE_NAV} .ember-basic-dropdown-content`;
const FOCUS_WALK_LIMIT = 40;
const SIDEBAR = ".hds-side-nav__wrapper";
const HOME_LINK = ".hds-side-nav__home-link";
const NAV_LINK = ".hds-side-nav__list-item-link";
const NAV_SELECTED = `${NAV_LINK}.active`;
const NAV_TITLE = ".hds-side-nav__list-title";
const MENU_TOGGLE = ".hds-side-nav__menu-toggle-button";
const USER_MENU = "button[aria-label='User menu']";
const USER_MENU_PANEL = ".sidebar-user-menu .popup-menu-content";
const CONSOLE_TOGGLE = "button[aria-label='Console toggle']";
const CONSOLE = ".panel-open .console-ui-panel";
const HEADING = "h1.title";
const ROW = ".list-item-row";
const EDITOR = ".CodeMirror";
const CODE = `${EDITOR} .CodeMirror-code`;
const SECRET_ROW = ".info-table-row:visible";
const NAMESPACE = `${SIDEBAR} .namespace-picker`;
const SHOWCASE_FOLDER = "design-showcase";
const SHOWCASE = {
  [`${SHOWCASE_FOLDER}/database`]: { username: "showcase", password: "dummy-value", host: "db.example.invalid" },
  [`${SHOWCASE_FOLDER}/api`]: { endpoint: "https://api.example.invalid", token: "dummy-value" },
};
const SHOWCASE_SECRET = `${SHOWCASE_FOLDER}/database`;

test.use({ ignoreHTTPSErrors: true });

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

/**
 * Args:
 *   page: Playwright page that shows the element.
 *   selector: element whose own background color is measured.
 *
 * Returns:
 *   The relative luminance of the computed background color of the first match.
 */
async function luminanceOf(page, selector) {
  return page
    .locator(selector)
    .first()
    .evaluate((element) => {
      const context = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
      context.fillStyle = getComputedStyle(element).backgroundColor;
      context.fillRect(0, 0, 1, 1);
      const [r, g, b] = [...context.getImageData(0, 0, 1, 1).data].slice(0, 3).map((channel) => {
        const share = channel / 255;
        return share <= 0.04045 ? share / 12.92 : ((share + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    });
}

function shown(selector) {
  return async (page) => {
    await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(60_000) });
    await page.waitForLoadState("networkidle");
    await animationsSettled(page);
  };
}

/**
 * Args:
 *   page: Playwright page to open the sign-in form of one auth method on.
 *   method: auth method the form preselects.
 */
async function openSignIn(page, method) {
  await gotoOnion(page, `${base}/ui/vault/auth?with=${method}`);
  await shown(SIGN_IN_FORM)(page);
}

/**
 * Args:
 *   page: Playwright page that ends signed in as the platform administrator through the password method the deployment provisions.
 */
async function signIn(page) {
  await openSignIn(page, passwordMount);
  const form = page.locator(SIGN_IN_FORM);
  await form.locator("#username").fill(adminUsername);
  await form.locator("#password").fill(adminPassword);
  await form.locator(SUBMIT).click();
  await expect(page.locator(HOME_LINK)).toBeVisible({ timeout: resolveTimeout(60_000) });
  await expect(page).toHaveURL(/\/ui\/vault\/secrets/);
}

/**
 * Args:
 *   page: Playwright page that shows the signed-in interface; a collapsed sidebar gets opened so its header controls are reachable.
 */
async function sidebarOpened(page) {
  if (!(await page.locator(USER_MENU).isVisible())) {
    await page.locator(MENU_TOGGLE).click();
    await expect(page.locator(USER_MENU)).toBeVisible();
  }
  await animationsSettled(page);
}

/**
 * Args:
 *   page: Playwright page that shows the opened side nav and ends with one of its entries focused through the keyboard.
 */
async function entryFocused(page) {
  await page.locator(NAV_LINK).first().focus();
  await page.keyboard.press("Tab");
  await expect(page.locator(`${NAV_LINK}:focus-visible`)).toHaveCount(1);
}

/**
 * Args:
 *   page: Playwright page whose focused element is inspected.
 *
 * Returns:
 *   The name of the focused element, whether the side nav holds it, whether a popup the side nav hosts holds it, and the distinct colors its focus indicator is drawn in: the box shadow of its `::before` box and its own outline, without fully transparent ones.
 */
async function focusStop(page) {
  return page.evaluate(
    ([sideNav, hostedPopup]) => {
      const element = document.activeElement;
      const own = getComputedStyle(element);
      const drawn = [
        ...(getComputedStyle(element, "::before").boxShadow.match(/rgba?\([^)]*\)/g) || []),
        ...(own.outlineStyle === "none" || parseFloat(own.outlineWidth) === 0 ? [] : [own.outlineColor]),
      ].filter((color) => !/^rgba\([^)]*,\s*0\)$/.test(color));
      return {
        name: [element.tagName.toLowerCase(), ...element.classList].join("."),
        framed: Boolean(element.closest(sideNav)),
        hosted: Boolean(element.closest(hostedPopup)),
        colors: [...new Set(drawn)],
      };
    },
    [SIDE_NAV, HOSTED_POPUP],
  );
}

/**
 * Args:
 *   page: Playwright page that shows the side nav on a freshly loaded document; the keyboard walks forward through every stop of the side nav outside the popups it hosts.
 *   mode: color scheme the failure messages name.
 */
async function assertFrameFocus(page, mode) {
  const ring = await tokenValue(page, "--design-on-frame", "color");
  const stops = [];
  for (let step = 0; step < FOCUS_WALK_LIMIT; step += 1) {
    await page.keyboard.press("Tab");
    const stop = await focusStop(page);
    if (!stop.framed && stops.length > 0) {
      break;
    }
    if (stop.framed && !stop.hosted) {
      stops.push(stop.name);
      await expect
        .poll(async () => (await focusStop(page)).colors, {
          message: `keyboard stop ${stop.name} of the side nav ${mode}: the focus indicator must be drawn in --design-on-frame`,
        })
        .toEqual([ring]);
    }
  }
  expect(stops.length, `the keyboard walk must find stops inside the side nav ${mode}`).toBeGreaterThan(0);
}

/**
 * Args:
 *   page: Playwright page that shows the side nav; the user menu it hosts gets opened, its first keyboard stop inspected and the menu closed again.
 *   mode: color scheme the failure messages name.
 */
async function assertHostedPopupFocus(page, mode) {
  const ring = await tokenValue(page, "--design-link", "color");
  await page.locator(USER_MENU).click();
  await expect(page.locator(USER_MENU_PANEL)).toBeVisible();
  await page.keyboard.press("Tab");
  const stop = await focusStop(page);
  expect(stop.hosted, `the keyboard must reach the user menu the side nav hosts ${mode}`).toBe(true);
  await expect
    .poll(async () => (await focusStop(page)).colors, {
      message: `keyboard stop ${stop.name} of the user menu ${mode}: the focus indicator must be drawn in --design-link`,
    })
    .toEqual([ring]);
  await page.locator(USER_MENU).click();
  await expect(page.locator(USER_MENU_PANEL)).toBeHidden();
}

/**
 * Args:
 *   request: Playwright API context that writes the showcase secrets the lists and detail views show, when they are missing.
 */
async function seedShowcase(request) {
  const login = await request.post(`${base}/v1/auth/${passwordMount}/login/${encodeURIComponent(adminUsername)}`, {
    data: { password: adminPassword },
    timeout: resolveTimeout(30_000),
  });
  expect(login.status(), "the administrator must obtain a token for seeding the showcase").toBe(200);
  const headers = { "X-Vault-Token": (await login.json()).auth.client_token };
  try {
    for (const [path, data] of Object.entries(SHOWCASE)) {
      const existing = await request.get(`${base}/v1/${kvMount}/metadata/${path}`, {
        headers,
        failOnStatusCode: false,
        timeout: resolveTimeout(30_000),
      });
      if (existing.status() === 404) {
        const created = await request.post(`${base}/v1/${kvMount}/data/${path}`, {
          headers,
          data: { data },
          timeout: resolveTimeout(30_000),
        });
        expect(created.ok(), `seeding the showcase secret ${path}`).toBe(true);
      }
    }
  } finally {
    await request.post(`${base}/v1/auth/token/revoke-self`, {
      headers,
      failOnStatusCode: false,
      timeout: resolveTimeout(30_000),
    });
  }
}

function signInViews() {
  const token = `${base}/ui/vault/auth?with=token`;
  const password = `${base}/ui/vault/auth?with=${passwordMount}`;
  return [
    { name: "sign-in", url: token, prepare: shown(SIGN_IN_FORM) },
    { name: "sign-in-password", url: password, prepare: shown(`${SIGN_IN_FORM} #username`) },
    {
      name: "sign-in-focus",
      url: password,
      prepare: async (page) => {
        await shown(`${SIGN_IN_FORM} #username`)(page);
        await page.locator(`${SIGN_IN_FORM} #username`).focus();
      },
    },
    {
      name: "sign-in-hover",
      url: password,
      prepare: async (page) => {
        await shown(SUBMIT)(page);
        await page.locator(SUBMIT).hover();
      },
    },
    {
      name: "sign-in-options",
      url: password,
      prepare: async (page) => {
        await shown(SIGN_IN_FORM)(page);
        await page.locator(MORE_OPTIONS).click();
        await shown("#custom-path")(page);
      },
    },
    {
      name: "sign-in-error",
      url: token,
      prepare: async (page) => {
        await shown(SIGN_IN_FORM)(page);
        await page.locator(`${SIGN_IN_FORM} input[name='token']`).fill("not-a-real-token");
        await page.locator(SUBMIT).click();
        await shown(".auth-form .message")(page);
      },
    },
  ];
}

function signedInViews() {
  const view = (name, path, selector) => ({ name, url: `${base}/ui/vault/${path}`, prepare: shown(selector) });
  const secrets = `${base}/ui/vault/secrets`;
  return [
    view("secrets-engines", "secrets", ROW),
    view("secrets-engine-enable", "settings/mount-secret-backend", HEADING),
    view("kv-list", `secrets/${kvMount}/list`, ROW),
    view("kv-folder", `secrets/${kvMount}/list/${SHOWCASE_FOLDER}/`, ROW),
    view("kv-secret", `secrets/${kvMount}/show/${SHOWCASE_SECRET}`, SECRET_ROW),
    {
      name: "kv-secret-json",
      url: `${base}/ui/vault/secrets/${kvMount}/show/${SHOWCASE_SECRET}`,
      prepare: async (page) => {
        await shown(SECRET_ROW)(page);
        await page.locator(".toolbar label", { hasText: "JSON" }).click();
        await shown(EDITOR)(page);
      },
    },
    view("kv-secret-create", `secrets/${kvMount}/create`, "form"),
    view("kv-secret-metadata", `secrets/${kvMount}/metadata/${SHOWCASE_SECRET}`, HEADING),
    view("kv-configuration", `secrets/${kvMount}/configuration`, ".info-table-row"),
    view("auth-methods", "access", ROW),
    view("auth-method-enable", "settings/auth/enable", HEADING),
    view("auth-method-configuration", `access/${passwordMount}/configuration`, ".info-table-row"),
    view("entities", "access/identity/entities", HEADING),
    view("groups", "access/identity/groups", ROW),
    view("group-create", "access/identity/groups/create", "form"),
    view("policies", "policies/acl", ROW),
    view("policy", "policy/acl/administrator", EDITOR),
    view("policy-create", "policies/acl/create", EDITOR),
    view("tools-wrap", "tools/wrap", EDITOR),
    view("tools-random", "tools/random", "form"),
    view("tools-hash", "tools/hash", "form"),
    {
      name: "user-menu",
      url: secrets,
      prepare: async (page) => {
        await shown(ROW)(page);
        await sidebarOpened(page);
        await page.locator(USER_MENU).click();
        await shown(USER_MENU_PANEL)(page);
      },
    },
    {
      name: "console",
      url: secrets,
      prepare: async (page) => {
        await shown(ROW)(page);
        await sidebarOpened(page);
        await page.locator(CONSOLE_TOGGLE).click();
        await shown(CONSOLE)(page);
      },
    },
    {
      name: "navigation",
      url: secrets,
      prepare: async (page) => {
        await shown(ROW)(page);
        await sidebarOpened(page);
        await page.locator(NAV_LINK, { hasText: "Policies" }).hover();
        await animationsSettled(page);
      },
    },
    {
      name: "navigation-focus",
      url: secrets,
      prepare: async (page) => {
        await shown(ROW)(page);
        await sidebarOpened(page);
        await entryFocused(page);
        await animationsSettled(page);
      },
    },
  ];
}

test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await openSignIn(page, "token");
  await assertDesignTokens(page, "openbao");
});

test("design: the sign-in page takes surface, primary action and text from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await openSignIn(page, "token");
    await assertToken(page, "html", "background-color", "--design-surface-1", `sign-in ${mode}`);
    await assertToken(page, SIGN_IN_BOX, "background-color", "--design-surface-2", `sign-in ${mode}`);
    await assertToken(page, HEADING, "color", "--design-text", `sign-in ${mode}`);
    await assertToken(page, `${SIGN_IN_FORM} label`, "color", "--design-text", `sign-in ${mode}`);
    await assertToken(page, `${SIGN_IN_FORM} .input`, "background-color", "--design-surface-2", `sign-in ${mode}`);
    await assertToken(page, `${SIGN_IN_FORM} .input`, "border-top-color", "--design-border-strong", `sign-in ${mode}`);
    await assertToken(page, SUBMIT, "background-color", "--design-primary", `sign-in ${mode}`);
    await assertToken(page, SUBMIT, "color", "--design-on-primary", `sign-in ${mode}`);
    await page.locator(SUBMIT).hover();
    await assertToken(page, SUBMIT, "background-color", "--design-primary-hover", `hovered sign-in ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await openSignIn(page, passwordMount || "token");
  await assertLightAndDark(page, SIGN_IN_BOX, "openbao sign-in");
  await assertReadable(
    page,
    [
      HEADING,
      `${SIGN_IN_FORM} label`,
      SUBMIT,
      { selector: MORE_OPTIONS, optional: !passwordMount },
      ".splash-page-container .help",
      "footer.footer",
      "footer.footer a",
    ],
    "openbao sign-in",
  );
});

test("design: the signed-in interface takes frame, surfaces, primary action and text from the palette", async ({
  page,
}) => {
  skipUnlessServiceEnabled("design");
  test.skip(!passwordMount, NO_PASSWORD_SIGN_IN);
  await signIn(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, `${base}/ui/vault/secrets`);
    await shown(ROW)(page);
    await assertToken(page, "html", "background-color", "--design-surface-1", `shell ${mode}`);
    await assertToken(page, SIDEBAR, "background-color", "--design-frame", `frame ${mode}`);
    await assertToken(page, NAV_LINK, "color", "--design-on-frame", `frame ${mode}`);
    await assertToken(page, NAV_SELECTED, "background-color", "--design-frame-active", `selected entry ${mode}`);
    await assertToken(page, HEADING, "color", "--design-text", `shell ${mode}`);
    await assertToken(page, `${ROW} a`, "color", "--design-text", `shell ${mode}`);
    const [frame, surface] = [await luminanceOf(page, SIDEBAR), await luminanceOf(page, "html")];
    if (mode === "light") {
      expect(frame, "the frame must be darker than the page in light mode").toBeLessThan(surface);
    } else {
      expect(frame, "the frame must differ from the page in dark mode").not.toBe(surface);
    }
    await page.locator(NAV_LINK, { hasText: "Policies" }).hover();
    await assertToken(
      page,
      `${NAV_LINK}:hover`,
      "background-color",
      "--design-frame-hover",
      `hovered navigation entry ${mode}`,
    );
    await assertFrameFocus(page, mode);
    await assertHostedPopupFocus(page, mode);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, ROW, "openbao shell");
  await assertReadable(
    page,
    [HEADING, `${ROW} a`, NAV_LINK, NAV_SELECTED, NAV_TITLE, NAMESPACE, ".toolbar-link", "footer.footer"],
    "openbao shell",
  );
});

test("design: the browser console and the code editor keep surface and text from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!passwordMount, NO_PASSWORD_SIGN_IN);
  await signIn(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, `${base}/ui/vault/policy/acl/administrator`);
    await shown(EDITOR)(page);
    await assertToken(page, EDITOR, "background-color", "--design-surface-3", `code editor ${mode}`);
    await page.locator(CONSOLE_TOGGLE).click();
    await shown(CONSOLE)(page);
    await assertToken(page, CONSOLE, "background-color", "--design-surface-3", `console ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, CONSOLE, "openbao console");
  await assertLightAndDark(page, EDITOR, "openbao code editor");
  await assertReadable(
    page,
    [`${CONSOLE} p`, `${CODE} .CodeMirror-line`, { selector: `${CODE} .cm-string`, optional: true }],
    "openbao code",
  );
});

test("design: the sign-in page shows the generated logo and the configured title", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");

  await openSignIn(page, "token");
  if (title) await expect(page).toHaveTitle(title);
  if (logoUrl) {
    expect(faviconUrl, "a role that renders a logo also renders DESIGN_FAVICON_URL").toBeTruthy();
    await expect(page.locator(BRAND)).toHaveCSS("background-image", `url("${logoUrl}")`);
    await expect(page.locator(`${BRAND} .hs-icon`)).toHaveCSS("visibility", "hidden");
    await expect(page.locator("link[rel~='icon']")).toHaveAttribute("href", faviconUrl);
    for (const url of [logoUrl, faviconUrl]) {
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
  }
});

test("design: the sidebar shows the generated logo and signed-in pages keep the configured title", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");
  test.skip(!passwordMount, NO_PASSWORD_SIGN_IN);

  await signIn(page);
  await gotoOnion(page, `${base}/ui/vault/policies/acl`);
  await shown(ROW)(page);
  if (title) await expect(page).toHaveTitle(title);
  if (logoUrl) {
    await expect(page.locator(HOME_LINK)).toHaveCSS("background-image", `url("${logoUrl}")`);
    await expect(page.locator(`${HOME_LINK} .hs-icon`)).toHaveCSS("visibility", "hidden");
    await expect(page.locator("link[rel~='icon']")).toHaveAttribute("href", faviconUrl);
  }
});

test("design: gallery of sign-in, secrets, access, policies, tools and menus", async ({ page, request }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
  test.skip(!passwordMount, NO_PASSWORD_SIGN_IN);
  test.setTimeout(resolveTimeout(2_400_000));

  await openSignIn(page, "token");
  await captureDesignGallery(page, signInViews());

  await seedShowcase(request);
  await signIn(page);
  await captureDesignGallery(page, signedInViews());
});
