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
const { apiFetchOnion, decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, performKeycloakLogin, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const base = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const canonicalDomain = requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN");
const adminEmail = requireDotenvValue(process.env.ADMIN_EMAIL, "ADMIN_EMAIL");
const adminPassword = requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD");
const adminUsername = requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME");
const ssoEnabled = process.env.SSO_SERVICE_ENABLED === "true";
const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
const logoWideUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_WIDE_URL || "");
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");

const MODES = ["light", "dark"];
const ORGANIZER = "design";
const EVENT = "showcase";
const BUYER = "showcase.buyer@example.org";
const CONTROL = `${base}/control`;
const EVENT_CONTROL = `${CONTROL}/event/${ORGANIZER}/${EVENT}`;
const API = `${base}/api/v1/organizers/${ORGANIZER}`;
const SIGN_IN_FORM = "form.form-signin";
const SUBMIT = `${SIGN_IN_FORM} button[type='submit'].btn-primary`;
const FRAME = "nav.navbar.navbar-inverse";
const BRAND = `${FRAME} .navbar-brand`;
const PAGE = "#page-wrapper";
const HEADING = `${PAGE} h1`;
const SHOP = "main#content";

test.use({ ignoreHTTPSErrors: true });

function shown(selector) {
  return async (page) => {
    await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
  };
}

function rgbToHex(rgb) {
  const channels = rgb.match(/\d+/g).slice(0, 3);
  return `#${channels.map((channel) => Number(channel).toString(16).padStart(2, "0")).join("")}`;
}

/**
 * Args:
 *   page: Playwright page that ends signed in to the control panel as the platform administrator,
 *   through Keycloak and pretix-oidc's staff mapping when sso is on.
 */
async function signIn(page) {
  if (ssoEnabled) {
    await gotoOnion(page, `${CONTROL}/login`);
    await page.locator("a[href*='openid-connect/auth']").first().click({ timeout: resolveTimeout(30_000) });
    await performKeycloakLogin(page, adminUsername, adminPassword, canonicalDomain);
  } else {
    await gotoOnion(page, `${CONTROL}/login?backend=native`);
    const email = page.locator(`${SIGN_IN_FORM} input[name='email']`);
    const password = page.locator(`${SIGN_IN_FORM} input[name='password']`);
    await expect(email).toBeEditable({ timeout: resolveTimeout(10_000) });
    await email.fill(adminEmail);
    await expect(password).toBeEditable({ timeout: resolveTimeout(10_000) });
    await password.fill(adminPassword);
    await page.locator(SUBMIT).click();
  }
  const alert = page.locator(`${SIGN_IN_FORM} .alert`);
  await expect(page.locator(`${FRAME}, ${SIGN_IN_FORM} .alert`).first(), `sign-in stalled on ${page.url()}`).toBeVisible({
    timeout: resolveTimeout(30_000),
  });
  await expect(alert, `sign-in rejected: ${(await alert.allInnerTexts()).join(" ")}`).toHaveCount(0);
}

/**
 * Args:
 *   page: signed-in page of a staff user; ends in an admin session that reaches every organizer.
 */
async function adminMode(page) {
  await gotoOnion(page, `${CONTROL}/`);
  const sudo = page.locator("#button-sudo");
  if ((await sudo.count()) > 0) {
    await sudo.evaluate((button) => button.closest("form").submit());
    await page.waitForLoadState("domcontentloaded");
  }
  await expect(page.locator(`${FRAME} a.admin-only`)).toBeAttached({ timeout: resolveTimeout(10_000) });
}

/**
 * Args:
 *   page: page in an admin session.
 *   method: HTTP method of the call.
 *   path: path below the organizer's API root.
 *   data: JSON body, or undefined.
 *   allowed: further statuses besides 2xx the caller handles itself.
 * Returns the status and the parsed JSON body; fails on any other status.
 */
async function apiCall(page, method, path, data, allowed) {
  const csrf = await page.locator("input[name='csrfmiddlewaretoken']").first().inputValue();
  const response = await apiFetchOnion(page.request, `${API}${path}`, {
    method,
    data,
    headers: {
      "X-CSRFToken": csrf,
      Referer: `${CONTROL}/`,
      "User-Agent": await page.evaluate(() => navigator.userAgent),
    },
    timeout: resolveTimeout(30_000),
  });
  const body = await response.text();
  expect(
    response.ok() || allowed.includes(response.status()),
    `${method} ${path} answered ${response.status()}: ${body.slice(0, 300)}`,
  ).toBe(true);
  return { status: response.status(), body: response.ok() && body ? JSON.parse(body) : {} };
}

async function api(page, method, path, data) {
  return (await apiCall(page, method, path, data, [])).body;
}

/**
 * Args:
 *   page: signed-in page of the platform administrator. Seeds the showcase
 *   organizer, an event with a category, three products, a quota, a
 *   voucher and two orders, idempotently.
 * Returns the code and secret of the paid showcase order.
 */
async function seedShowcase(page) {
  await adminMode(page);
  await gotoOnion(page, `${CONTROL}/settings`);
  const organizer = await apiCall(page, "GET", "/", undefined, [403, 404]);
  if (organizer.status !== 200) {
    await gotoOnion(page, `${CONTROL}/organizers/add`);
    await page.locator(`${PAGE} input[name='name']`).fill("Design Showcase");
    await page.locator(`${PAGE} input[name='slug']`).fill(ORGANIZER);
    await page.locator(`${PAGE} form button[type='submit'].btn-primary`).click();
    await expect(page).toHaveURL(new RegExp(`/control/organizer/${ORGANIZER}/`), { timeout: resolveTimeout(10_000) });
    await gotoOnion(page, `${CONTROL}/settings`);
  }
  const events = await api(page, "GET", `/events/?slug=${EVENT}`);
  if (!events.results.some((event) => event.slug === EVENT)) {
    await api(page, "POST", "/events/", {
      name: { en: "Showcase Conference" },
      slug: EVENT,
      currency: "EUR",
      date_from: "2027-06-01T09:00:00Z",
      date_to: "2027-06-02T18:00:00Z",
      location: { en: "Design Hall" },
      live: false,
    });
  }
  const ev = `/events/${EVENT}`;
  const categories = await api(page, "GET", `${ev}/categories/`);
  const category =
    categories.results[0] || (await api(page, "POST", `${ev}/categories/`, { name: { en: "Tickets" }, position: 0 }));
  const items = await api(page, "GET", `${ev}/items/`);
  const wanted = [
    { name: "Conference Pass", price: "149.00", admission: true },
    { name: "Workshop Day", price: "89.00", admission: true },
    { name: "Event T-Shirt", price: "25.00", admission: false },
  ];
  const itemIds = [];
  for (const entry of wanted) {
    const found = items.results.find((item) => item.name.en === entry.name);
    const item =
      found ||
      (await api(page, "POST", `${ev}/items/`, {
        name: { en: entry.name },
        default_price: entry.price,
        category: category.id,
        admission: entry.admission,
        active: true,
      }));
    itemIds.push(item.id);
  }
  const quotas = await api(page, "GET", `${ev}/quotas/`);
  if (quotas.count === 0) {
    await api(page, "POST", `${ev}/quotas/`, { name: "Main quota", size: 200, items: itemIds });
  }
  const vouchers = await api(page, "GET", `${ev}/vouchers/`);
  if (vouchers.count === 0) {
    await api(page, "POST", `${ev}/vouchers/`, {
      code: "DESIGN2027",
      max_usages: 10,
      price_mode: "percent",
      value: "10.00",
      item: null,
    });
  }
  const orders = await api(page, "GET", `${ev}/orders/?email=${encodeURIComponent(BUYER)}`);
  let paid = orders.results.find((order) => order.status === "p");
  if (orders.count === 0) {
    paid = await api(page, "POST", `${ev}/orders/`, {
      email: BUYER,
      locale: "en",
      status: "p",
      payment_provider: "manual",
      positions: [{ item: itemIds[0], price: "149.00", attendee_name_parts: { full_name: "Ada Showcase" } }],
    });
    await api(page, "POST", `${ev}/orders/`, {
      email: BUYER,
      locale: "en",
      status: "n",
      payment_provider: "manual",
      positions: [{ item: itemIds[1], price: "89.00", attendee_name_parts: { full_name: "Grace Showcase" } }],
    });
  }
  return { code: paid.code, secret: paid.secret };
}

test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await gotoOnion(page, `${CONTROL}/login`);
  await shown(SIGN_IN_FORM)(page);
  await assertDesignTokens(page, "pretix");
});

test("design: the upstream default account is locked against its published and the administrator password", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  for (const secret of ["admin", adminPassword]) {
    await gotoOnion(page, `${CONTROL}/login?backend=native`);
    const email = page.locator(`${SIGN_IN_FORM} input[name='email']`);
    const password = page.locator(`${SIGN_IN_FORM} input[name='password']`);
    await expect(email).toBeEditable({ timeout: resolveTimeout(10_000) });
    await email.fill("admin@localhost");
    await expect(password).toBeEditable({ timeout: resolveTimeout(10_000) });
    await password.fill(secret);
    await page.locator(SUBMIT).click();
    await expect(page.locator(`${SIGN_IN_FORM} .alert-danger`)).toBeVisible({ timeout: resolveTimeout(10_000) });
    await expect(page.locator(FRAME)).toHaveCount(0);
  }
});

test("design: the sign-in page takes surface, primary action and text from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, `${CONTROL}/login`);
    await shown(SIGN_IN_FORM)(page);
    await assertToken(page, "body", "background-color", "--design-surface-1", `sign-in ${mode}`);
    await assertToken(page, SIGN_IN_FORM, "background-color", "--design-surface-2", `sign-in ${mode}`);
    await assertToken(page, `${SIGN_IN_FORM} label`, "color", "--design-text", `sign-in ${mode}`);
    await assertToken(page, `${SIGN_IN_FORM} .form-control`, "border-top-color", "--design-border-strong", `sign-in ${mode}`);
    await assertToken(page, SUBMIT, "background-color", "--design-primary", `sign-in ${mode}`);
    await assertToken(page, SUBMIT, "color", "--design-on-primary", `sign-in ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, SIGN_IN_FORM, "pretix sign-in");
  await assertReadable(page, [`${SIGN_IN_FORM} label`, SUBMIT, { selector: `${SIGN_IN_FORM} .btn-link`, optional: true }], "pretix sign-in");
});

test("design: the control panel takes frame, surfaces and text from the palette", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, `${CONTROL}/settings`);
    await shown(`${PAGE} form`)(page);
    await assertToken(page, FRAME, "background-color", "--design-frame", `frame ${mode}`);
    await assertToken(page, `${BRAND} span`, "color", "--design-on-frame", `frame ${mode}`);
    await assertToken(page, PAGE, "background-color", "--design-surface-2", `page ${mode}`);
    await assertToken(page, `${PAGE} label`, "color", "--design-text", `page ${mode}`);
    await assertToken(page, `${PAGE} .form-control`, "border-top-color", "--design-border-strong", `page ${mode}`);
    await assertToken(page, `${PAGE} .btn-primary`, "background-color", "--design-primary", `page ${mode}`);
    await assertToken(page, `${PAGE} .btn-primary`, "color", "--design-on-primary", `page ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, PAGE, "pretix control");
  await assertReadable(page, [`${PAGE} label`, `${BRAND} span`, `${PAGE} .btn-primary`, { selector: `${PAGE} .help-block`, optional: true }], "pretix control");
});

test("design: every focus stop in the top bar draws its indicator in --design-on-frame", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await gotoOnion(page, `${CONTROL}/settings`);
  await shown(`${PAGE} form`)(page);
  const expected = await tokenValue(page, "--design-on-frame", "outline-color");
  await page.locator("body").focus();
  const stops = [];
  for (let step = 0; step < 12; step += 1) {
    await page.keyboard.press("Tab");
    const stop = await page.evaluate((frame) => {
      const active = document.activeElement;
      if (!active || !active.closest(frame) || active.closest(".sidebar")) return null;
      const style = getComputedStyle(active);
      return { label: active.textContent.trim().slice(0, 30), color: style.outlineColor, style: style.outlineStyle };
    }, FRAME);
    if (stop) stops.push(stop);
  }
  expect(stops.length, "the top bar must hold focus stops").toBeGreaterThan(0);
  for (const stop of stops) {
    expect(stop.style, `top bar focus stop '${stop.label}' draws no outline`).not.toBe("none");
    expect(stop.color, `top bar focus stop '${stop.label}' outline color`).toBe(expected);
  }
});

test("design: the admin session control and the event status cells stay readable", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await seedShowcase(page);
  await gotoOnion(page, `${CONTROL}/`);
  await shown(".widget-container-event .bottomrow a[class*='status-']")(page);
  await assertReadable(
    page,
    [`${FRAME} a.danger`, ".widget-container-event .bottomrow a.orders", ".widget-container-event .bottomrow a[class*='status-']"],
    "pretix dashboard",
  );
});

test("design: a table row divider equals --design-border in both modes", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, `${CONTROL}/settings/notifications/`);
    await shown(`${PAGE} table td`)(page);
    await assertToken(page, `${PAGE} table td`, "border-top-color", "--design-border", `divider ${mode}`);
  }
});

test("design: the shop takes the light palette from the in-house theme and the active mode from the tokens", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  await signIn(page);
  await seedShowcase(page);
  const primary = rgbToHex(await tokenValue(page, "--design-primary", "color"));
  const theme = await apiFetchOnion(page.request, `${base}/${ORGANIZER}/theme.css`, { timeout: resolveTimeout(30_000) });
  expect((await theme.text()).toLowerCase(), "the in-house shop theme must carry the light --design-primary").toContain(
    `--pretix-brand-primary: ${primary}`,
  );
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await gotoOnion(page, `${base}/${ORGANIZER}/${EVENT}/`);
    await shown(`${SHOP} form`)(page);
    await assertToken(page, "body", "background-color", "--design-surface-1", `shop ${mode}`);
    await assertToken(page, `${SHOP} .btn-primary`, "background-color", "--design-primary", `shop ${mode}`);
    await assertToken(page, `${SHOP} .btn-primary`, "color", "--design-on-primary", `shop ${mode}`);
  }
  await page.emulateMedia({ colorScheme: null });
  await assertLightAndDark(page, SHOP, "pretix shop");
  await assertReadable(page, [`${SHOP} h2`, `${SHOP} .btn-primary`], "pretix shop");
});

test("design: logo and title come from the corporate design", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");
  await gotoOnion(page, `${CONTROL}/login`);
  if (title) await expect(page).toHaveTitle(title);
  if (logoWideUrl) {
    await expect(page.locator("img.logo")).toHaveCSS("content", `url("${logoWideUrl}")`);
    const box = await page.locator("img.logo").boundingBox();
    expect(box.width, "the sign-in lockup must be wider than high").toBeGreaterThan(box.height);
  }
  await signIn(page);
  if (title) await expect(page.locator(`${BRAND} span`)).toHaveText(title);
  if (logoUrl) await expect(page.locator(`${BRAND} img`)).toHaveCSS("content", `url("${logoUrl}")`);
});

test("design: gallery of control panel and shop", async ({ page }) => {
  skipUnlessServiceEnabled("design");
  test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
  test.setTimeout(resolveTimeout(2_400_000));
  const view = (name, url, selector) => ({ name, url, prepare: shown(selector) });
  const failures = [];
  await captureDesignGallery(page, [
    view("root", `${base}/`, "img.logo"),
    view("sign-in", `${CONTROL}/login`, SIGN_IN_FORM),
    {
      name: "sign-in-error",
      url: `${CONTROL}/login?backend=native`,
      prepare: async (current) => {
        await current.locator(`${SIGN_IN_FORM} input[name='email']`).fill("nobody@example.org");
        await current.locator(`${SIGN_IN_FORM} input[name='password']`).fill("not-a-password");
        await current.locator(SUBMIT).click();
        await shown(`${SIGN_IN_FORM} .alert-danger`)(current);
      },
    },
    view("password-forgot", `${CONTROL}/forgot`, SIGN_IN_FORM),
  ]).catch((error) => failures.push(error.message));
  await signIn(page);
  const order = await seedShowcase(page);
  await captureDesignGallery(page, [
    view("dashboard", `${CONTROL}/`, PAGE),
    view("account-settings", `${CONTROL}/settings`, `${PAGE} form`),
    view("account-2fa", `${CONTROL}/settings/2fa/`, HEADING),
    view("account-notifications", `${CONTROL}/settings/notifications/`, `${PAGE} table`),
    view("organizers", `${CONTROL}/organizers/`, `${PAGE} table`),
    view("organizer", `${CONTROL}/organizer/${ORGANIZER}/`, HEADING),
    view("organizer-edit", `${CONTROL}/organizer/${ORGANIZER}/edit`, `${PAGE} form`),
    view("teams", `${CONTROL}/organizer/${ORGANIZER}/teams`, `${PAGE} table`),
    view("events", `${CONTROL}/events/`, `${PAGE} table`),
    view("event-dashboard", `${EVENT_CONTROL}/`, HEADING),
    {
      name: "event-switcher-open",
      url: `${EVENT_CONTROL}/`,
      prepare: async (current) => {
        const toggle = current.locator(`${FRAME} .navbar-header .navbar-toggle[data-toggle='collapse']`);
        if (await toggle.isVisible()) {
          await toggle.click();
          await shown(".context-selector .dropdown-toggle")(current);
        }
        await current.locator(".context-selector .dropdown-toggle").click();
        await shown(".context-selector.open .dropdown-menu")(current);
      },
    },
    view("event-settings", `${EVENT_CONTROL}/settings/`, `${PAGE} form`),
    view("event-display", `${EVENT_CONTROL}/settings/display`, `${PAGE} form`),
    view("items", `${EVENT_CONTROL}/items/`, `${PAGE} table`),
    view("quotas", `${EVENT_CONTROL}/quotas/`, `${PAGE} table`),
    view("vouchers", `${EVENT_CONTROL}/vouchers/`, `${PAGE} table`),
    view("orders", `${EVENT_CONTROL}/orders/`, `${PAGE} table`),
    view("order", `${EVENT_CONTROL}/orders/${order.code}/`, HEADING),
    view("global-settings", `${CONTROL}/global/settings/`, `${PAGE} form`),
    view("users", `${CONTROL}/users/`, `${PAGE} table`),
    view("shop-organizer", `${base}/${ORGANIZER}/`, SHOP),
    view("shop-event", `${base}/${ORGANIZER}/${EVENT}/`, `${SHOP} form`),
    view("shop-voucher", `${base}/${ORGANIZER}/${EVENT}/redeem?voucher=DESIGN2027`, SHOP),
    view("shop-order", `${base}/${ORGANIZER}/${EVENT}/order/${order.code}/${order.secret}/`, SHOP),
  ]).catch((error) => failures.push(error.message));
  expect(failures, failures.join("\n")).toEqual([]);
});
