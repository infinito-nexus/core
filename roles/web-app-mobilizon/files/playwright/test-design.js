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
const { performKeycloakLogin } = require("./personas/utils/keycloak");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const base = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const canonicalDomain = requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN");
const adminEmail = requireDotenvValue(process.env.ADMIN_EMAIL, "ADMIN_EMAIL");
const adminPassword = requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD");
const adminUsername = requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME");
const faviconUrl = requireDotenvValue(process.env.DESIGN_FAVICON_URL, "DESIGN_FAVICON_URL");
const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
const ssoEnabled = process.env.SSO_SERVICE_ENABLED === "true";

const MODES = ["light", "dark"];
const MAIN = "main#main";
const NAVBAR = "#navbar";
const FOOTER = "footer.bg-violet-2";
const LOGIN_EMAIL = "#email";
const LOGIN_PASSWORD = "#password";
const LOGIN_SUBMIT = `${MAIN} form button[type=submit]`;
const USER_MENU = "#user-menu-button";
const TABLE_ROW = `${MAIN} table tbody tr`;
const SHOWCASE_GROUP = "design_showcase";
const SHOWCASE_EVENTS = ["Design showcase meetup", "Design showcase workshop"];

test.use({ ignoreHTTPSErrors: true, serviceWorkers: "block" });

/**
 * Args:
 *   selector: element whose visibility marks the view as ready.
 */
function shown(selector) {
  return async (page) => {
    await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
    await expect(page.locator(".o-loading__overlay")).toHaveCount(0, { timeout: resolveTimeout(10_000) });
  };
}

/**
 * Args:
 *   page: Playwright page that ends signed in as the platform administrator, through Keycloak when sso is on.
 */
async function signIn(page) {
  await gotoOnion(page, `${base}/login`);
  if (ssoEnabled) {
    await page.locator(`${MAIN} a[href*='/auth/']`).first().click({ timeout: resolveTimeout(30_000) });
    await performKeycloakLogin(page, adminUsername, adminPassword, canonicalDomain);
    await gotoOnion(page, `${base}/`);
  } else {
    const email = page.locator(LOGIN_EMAIL);
    const password = page.locator(LOGIN_PASSWORD);
    await expect(email).toBeEditable({ timeout: resolveTimeout(30_000) });
    await email.fill(adminEmail);
    await expect(password).toBeEditable({ timeout: resolveTimeout(10_000) });
    await password.fill(adminPassword);
    await page.locator(LOGIN_SUBMIT).click();
  }
  await expect(page.locator(USER_MENU)).toBeVisible({ timeout: resolveTimeout(30_000) });
}

/**
 * Args:
 *   page: signed-in page whose access token authorizes the call.
 *   query: GraphQL document.
 *   variables: GraphQL variables.
 */
async function graphql(page, query, variables = {}) {
  const body = await page.evaluate(
    async ([document, values]) => {
      const response = await fetch("/api", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          authorization: `Bearer ${localStorage.getItem("auth-access-token")}`,
        },
        body: JSON.stringify({ query: document, variables: values }),
      });
      return response.json();
    },
    [query, variables],
  );
  expect(body.errors, JSON.stringify(body.errors)).toBeUndefined();
  return body.data;
}

/**
 * Args:
 *   page: page whose document receives a throwaway element carrying the given classes.
 *   classes: class names of the app's compiled utilities to measure.
 *   property: computed CSS property to read.
 */
async function utilityValue(page, classes, property) {
  return page.evaluate(
    ([names, cssProperty]) => {
      const probe = document.createElement("span");
      probe.className = names;
      document.body.appendChild(probe);
      const value = getComputedStyle(probe).getPropertyValue(cssProperty);
      probe.remove();
      return value;
    },
    [classes, property],
  );
}

test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await gotoOnion(page, `${base}/about/instance`);
  await shown(`${MAIN} h1`)(page);
  await assertDesignTokens(page, "mobilizon");
});

test("design: public pages take page, panel, text, field, primary action and footer frame from the palette", async ({
  page,
}) => {
  skipUnlessServiceEnabled("design");
  const field = `${MAIN} input[type=email]`;
  const action = `${MAIN} form .btn-primary`;
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, `${base}/password-reset/send`);
    await shown(field)(page);
    await assertToken(page, "body", "background-color", "--design-surface-1", `page ${mode}`);
    await assertToken(page, NAVBAR, "background-color", "--design-surface-2", `navbar ${mode}`);
    await assertToken(page, `${MAIN} h1`, "color", "--design-text", `heading ${mode}`);
    await assertToken(page, field, "background-color", "--design-surface-2", `field ${mode}`);
    await assertToken(page, field, "border-top-color", "--design-border-strong", `field border ${mode}`);
    await assertToken(page, action, "background-color", "--design-primary", `primary action ${mode}`);
    await assertToken(page, action, "color", "--design-on-primary", `primary action text ${mode}`);
    await page.locator(action).hover();
    await assertToken(page, action, "background-color", "--design-primary-hover", `hovered primary action ${mode}`);
    await assertToken(page, FOOTER, "background-color", "--design-frame", `footer ${mode}`);
    await assertToken(page, `${FOOTER} a`, "color", "--design-on-frame", `footer link ${mode}`);
    await assertToken(page, FOOTER, "--design-focus", "--design-on-frame", `footer focus ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, `${MAIN} h1`, "mobilizon password reset");
  await assertReadable(page, [`${MAIN} h1`, `${MAIN} label`, action, `${FOOTER} a`], "mobilizon password reset");
});

test("design: the about hero that upstream fills with the primary color sits on the frame", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  const hero = `${MAIN} section.bg-primary`;
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, `${base}/about/instance`);
    await shown(`${hero} h1`)(page);
    await assertToken(page, hero, "background-color", "--design-frame", `about hero ${mode}`);
    await assertToken(page, `${hero} h1`, "color", "--design-on-frame", `about hero heading ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertReadable(page, [`${hero} h1`], "mobilizon about hero");
});

test("design: every focus stop in the footer frame draws its outline in the frame text color", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await gotoOnion(page, `${base}/about/instance`);
  await shown(FOOTER)(page);
  const expected = await tokenValue(page, "--design-on-frame", "outline-color");
  const inFooter = () => page.evaluate((footer) => !!document.activeElement?.closest(footer), FOOTER);
  for (let step = 0; step < 80 && !(await inFooter()); step += 1) {
    await page.keyboard.press("Tab");
  }
  let stops = 0;
  for (let step = 0; step < 30; step += 1) {
    const state = await page.evaluate((footer) => {
      const active = document.activeElement;
      if (!active || !active.closest(footer)) return null;
      const style = getComputedStyle(active);
      return { color: style.outlineColor, style: style.outlineStyle };
    }, FOOTER);
    if (state === null) break;
    stops += 1;
    expect(state.style, `footer focus stop ${stops} draws an outline`).not.toBe("none");
    expect(state.color, `footer focus stop ${stops} outline color`).toBe(expected);
    await page.keyboard.press("Tab");
  }
  expect(stops, "the footer frame holds focus stops").toBeGreaterThan(0);
});

test("design: the provisioned administrator signs in and reaches the administration", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await gotoOnion(page, `${base}/settings/admin/dashboard`);
  await shown(`${MAIN} h1`)(page);
  await expect(page.locator(`${MAIN} h1`).first()).not.toHaveText(/not found|404/i);
});

test("design: the instance settings carry the light primary and the role stylesheet carries dark mode", async ({
  page,
}) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, `${base}/settings/admin/users`);
    await shown(TABLE_ROW)(page);
    await expect(page.locator("html")).toHaveAttribute("style", /--custom-primary/, { timeout: resolveTimeout(10_000) });
    const primary = await tokenValue(page, "--design-primary", "background-color");
    if (mode === "light") {
      const custom = await page.evaluate(() => {
        const probe = document.createElement("span");
        probe.style.backgroundColor = getComputedStyle(document.documentElement).getPropertyValue("--custom-primary");
        document.body.appendChild(probe);
        const value = getComputedStyle(probe).backgroundColor;
        probe.remove();
        return value;
      });
      expect(custom, "the instance primary color equals the light --design-primary").toBe(primary);
    }
    for (const classes of ["bg-primary", "pagination-link-current", "switch-check-checked", "btn"]) {
      expect(await utilityValue(page, classes, "background-color"), `${classes} ${mode}`).toBe(primary);
    }
    expect(await utilityValue(page, "btn", "color"), `btn text ${mode}`).toBe(
      await tokenValue(page, "--design-on-primary", "color"),
    );
    expect(await utilityValue(page, "text-primary", "color"), `text-primary ${mode}`).toBe(
      await tokenValue(page, "--design-link", "color"),
    );
    await assertToken(page, `${TABLE_ROW}:nth-child(odd)`, "background-color", "--design-surface-2", `table ${mode}`);
    await assertToken(page, `${TABLE_ROW} td`, "border-bottom-color", "--design-border", `divider ${mode}`);
    await assertToken(page, `${MAIN} h1`, "color", "--design-text", `heading ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, TABLE_ROW, "mobilizon admin table");
  await assertReadable(page, [`${MAIN} h1`, `${TABLE_ROW} td`], "mobilizon admin table");
});

test("design: the native theme switch drives the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await page.emulateMedia({ colorScheme: "light" });
  await gotoOnion(page, `${base}/settings/preferences`);
  await shown(`${MAIN} input[name=theme]`)(page);
  const html = page.locator("html");
  await expect(html).not.toHaveAttribute("data-design-theme", /.+/);
  const system = page.locator(`${MAIN} input[type=checkbox]`).first();
  await system.uncheck({ force: true });
  await page.locator(`${MAIN} input[name=theme][value=dark]`).check({ force: true });
  await expect(html).toHaveClass(/\bdark\b/);
  await expect(html).toHaveAttribute("data-design-theme", "dark");
  await gotoOnion(page, `${base}/settings/preferences`);
  await shown(`${MAIN} input[name=theme]`)(page);
  await expect(html).toHaveAttribute("data-design-theme", "dark");
  const surface = await tokenValue(page, "--design-surface-1", "background-color");
  await page.emulateMedia({ colorScheme: "dark" });
  expect(await tokenValue(page, "--design-surface-1", "background-color")).toBe(surface);
  await page.emulateMedia({ colorScheme: "light" });
  await assertToken(page, "body", "background-color", "--design-surface-1", "forced dark");
  await system.check({ force: true });
  await expect(html).not.toHaveAttribute("data-design-theme", /.+/);
});

test("design: the navbar shows the generated logo and the instance carries the configured title and favicon", async ({
  page,
}) => {
  skipUnlessServiceEnabled("design");
  await gotoOnion(page, `${base}/`);
  await shown(NAVBAR)(page);
  await expect(page).toHaveTitle(title, { timeout: resolveTimeout(10_000) });
  test.skip(!logoUrl, "logo replacement is disabled for this role");
  const logo = page.locator(`${NAVBAR} a[href='/'] img`);
  await expect(logo).toBeVisible({ timeout: resolveTimeout(10_000) });
  await expect(logo).toHaveAttribute("src", logoUrl);
  await expect.poll(() => logo.evaluate((image) => image.complete && image.naturalWidth > 0)).toBe(true);
  const box = await logo.boundingBox();
  expect(box.width, "the navbar lockup must be wider than high").toBeGreaterThan(box.height * 2);
  await expect(page.locator("link[rel=icon]").first()).toHaveAttribute("href", faviconUrl);
});

/**
 * Args:
 *   name: view name.
 *   path: route below the app base URL.
 *   selector: element whose visibility marks the view as ready.
 */
function view(name, path, selector) {
  return { name, url: `${base}${path}`, prepare: shown(selector) };
}

function visitorViews() {
  const views = [
    view("home", "/", `${MAIN} h1, ${MAIN} h2`),
    view("search", "/search", `${MAIN} a[href*='/events/']`),
    view("categories", "/categories", `${MAIN} h1`),
    view("about-instance", "/about/instance", `${MAIN} h1`),
    view("rules", "/rules", `${MAIN} h1`),
    view("login", "/login", `${MAIN} h1`),
    view("password-reset", "/password-reset/send", `${MAIN} input[type=email]`),
    view("not-found", "/404", `${MAIN} h1`),
  ];
  if (!ssoEnabled) {
    views.splice(6, 0, {
      name: "login-error",
      url: `${base}/login`,
      prepare: async (page) => {
        await shown(LOGIN_EMAIL)(page);
        await page.locator(LOGIN_EMAIL).fill("nobody@example.invalid");
        await page.locator(LOGIN_PASSWORD).fill(`wrong-${Date.now()}`);
        await page.locator(LOGIN_SUBMIT).click();
        await shown(`${MAIN} .notification-danger`)(page);
      },
    });
  }
  return views;
}

/**
 * Args:
 *   eventUuid: uuid of the seeded showcase event.
 */
function signedInViews(eventUuid) {
  return [
    view("event", `/events/${eventUuid}`, `${MAIN} h1`),
    view("my-events", "/events/me", `${MAIN} h1`),
    view("event-create", "/events/create", `${MAIN} form`),
    view("my-groups", "/groups/me", `${MAIN} h1`),
    view("group", `/@${SHOWCASE_GROUP}`, `${MAIN} h1`),
    view("group-create", "/groups/create", `${MAIN} form input`),
    view("settings-account", "/settings/account/general", `${MAIN} input[type=email]`),
    view("settings-preferences", "/settings/preferences", `${MAIN} input[name=theme]`),
    view("settings-notifications", "/settings/notifications", `${MAIN} input[type=checkbox]`),
    view("admin-dashboard", "/settings/admin/dashboard", `${MAIN} h1`),
    view("admin-settings", "/settings/admin/settings", `${MAIN} form`),
    view("admin-users", "/settings/admin/users", TABLE_ROW),
    view("admin-profiles", "/settings/admin/profiles", `${MAIN} table`),
    view("admin-groups", "/settings/admin/groups", `${MAIN} table`),
    view("moderation-reports", "/moderation/reports", `${MAIN} h1`),
    {
      name: "user-menu",
      url: `${base}/events/me`,
      prepare: async (page) => {
        await shown(USER_MENU)(page);
        await page.locator(USER_MENU).click();
        const panel = page.locator(".dropdown-menu").first();
        await expect(panel).toBeVisible({ timeout: resolveTimeout(10_000) });
        await expect
          .poll(() => panel.evaluate((element) => getComputedStyle(element).opacity === "1" && element.getAnimations({ subtree: true }).length === 0), {
            timeout: resolveTimeout(10_000),
          })
          .toBe(true);
      },
    },
  ];
}

/**
 * Args:
 *   page: page signed in as the platform administrator; returns the uuid of the first showcase event.
 */
async function seedShowcase(page) {
  const me = await graphql(page, "{ loggedPerson { id } }");
  const actorId = me.loggedPerson.id;
  const group = await graphql(page, "query($name: String!) { group(preferredUsername: $name) { id } }", {
    name: SHOWCASE_GROUP,
  }).catch(() => ({ group: null }));
  if (!group.group) {
    await graphql(
      page,
      "mutation($name: String!, $title: String!) { createGroup(preferredUsername: $name, name: $title, summary: $title) { id } }",
      { name: SHOWCASE_GROUP, title: "Design showcase" },
    );
  }
  const own = await graphql(page, "{ loggedPerson { organizedEvents(limit: 50) { elements { uuid title } } } }");
  const known = own.loggedPerson.organizedEvents.elements;
  for (const [index, eventTitle] of SHOWCASE_EVENTS.entries()) {
    if (known.some((event) => event.title === eventTitle)) continue;
    const beginsOn = new Date(Date.now() + (index + 3) * 86_400_000).toISOString();
    await graphql(
      page,
      "mutation($actor: ID!, $title: String!, $beginsOn: DateTime!, $description: String!) { createEvent(organizerActorId: $actor, title: $title, beginsOn: $beginsOn, description: $description) { uuid } }",
      { actor: actorId, title: eventTitle, beginsOn, description: `<p>${eventTitle} of the corporate design review.</p>` },
    );
  }
  const seeded = await graphql(page, "{ loggedPerson { organizedEvents(limit: 50) { elements { uuid title } } } }");
  return seeded.loggedPerson.organizedEvents.elements.find((event) => event.title === SHOWCASE_EVENTS[0]).uuid;
}

test("design: gallery of public pages, account, settings and administration", async ({ page, browser }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
  test.setTimeout(resolveTimeout(840_000));
  const failures = [];
  const seeder = await browser.newContext({ ignoreHTTPSErrors: true, serviceWorkers: "block" });
  const seedPage = await seeder.newPage();
  await signIn(seedPage);
  const eventUuid = await seedShowcase(seedPage);
  await seeder.close();
  await captureDesignGallery(page, visitorViews()).catch((error) => failures.push(error.message));
  await signIn(page);
  await captureDesignGallery(page, signedInViews(eventUuid)).catch((error) => failures.push(error.message));
  expect(failures, failures.join("\n")).toEqual([]);
});
