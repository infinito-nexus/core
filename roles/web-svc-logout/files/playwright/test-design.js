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
const { apiGetOnion, decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const MODES = ["light", "dark"];
const SWEEP = "**/logout?t=*";
const HOLD_MS = 20_000;
const READY_MS = 10_000;
const HEADING = "h1";
const STATUS = "#status-0";
const PENDING = "td.status-in-process";
const FAILED = "td.status-failure";
const DONE = "td.status-success";
const SERVICE_LINK = "tbody td a:not(.btn)";
const MANUAL = "a.manual-logout-link";
const SOURCE_LINK = "p.mt-4 a";
const WARNING = "#iframe-warning";
const HEAD_CELL = "thead th";
const BODY_CELL = "tbody td";

function base() {
  return decodeDotenvQuotedValue(process.env.APP_BASE_URL).replace(/\/$/, "");
}

function designTitle() {
  return decodeDotenvQuotedValue(process.env.DESIGN_TITLE);
}

function designFaviconUrl() {
  return decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL);
}

function conductorUrl(lang, sweep) {
  return `${base()}/?lang=${lang}&sweep=${sweep}`;
}

/**
 * Args:
 *   state: the `sweep` parameter of the conductor URL: "done", "failed", "pending" or "mixed".
 *   host: host name the sweep request goes to.
 */
function outcome(state, host) {
  if (state !== "mixed") return state;
  if (host === new URL(base()).hostname) return "pending";
  return host.split(".")[0].length % 2 === 0 ? "failed" : "done";
}

async function answerSweep(route) {
  const request = route.request();
  let origin;
  let state;
  try {
    const conductor = new URL(request.frame().url());
    origin = conductor.origin;
    state = conductor.searchParams.get("sweep");
  } catch {
    state = null;
  }
  if (!state) return route.continue();
  const result = outcome(state, new URL(request.url()).hostname);
  if (result === "failed") return route.abort();
  if (result === "pending") {
    setTimeout(() => route.abort().catch(() => {}), resolveTimeout(HOLD_MS));
    return undefined;
  }
  return route.fulfill({
    status: 200,
    contentType: "text/plain",
    body: "ok",
    headers: { "access-control-allow-credentials": "true", "access-control-allow-origin": origin },
  });
}

/**
 * Args:
 *   target: Playwright page or frame that shows the conductor.
 *   state: the forced sweep state the rows must reach.
 */
async function shows(target, state) {
  await target.locator(HEADING).waitFor({ state: "visible", timeout: resolveTimeout(READY_MS) });
  await target.waitForFunction(
    (wanted) => {
      const rows = document.querySelectorAll("tbody tr").length;
      const count = (selector) => document.querySelectorAll(selector).length;
      const [pending, failed, done] = ["td.status-in-process", "td.status-failure", "td.status-success"].map(count);
      if (wanted === "pending") return rows > 0 && pending === rows;
      if (wanted === "failed") return rows > 0 && failed === rows;
      if (wanted === "done") return rows > 0 && done === rows;
      return rows > 0 && pending <= 1 && failed + done >= rows - 1;
    },
    state,
    { timeout: resolveTimeout(READY_MS) },
  );
}

/**
 * Args:
 *   page: Playwright page.
 *   lang: language code of the conductor.
 *   sweep: forced sweep state.
 */
async function openConductor(page, lang, sweep) {
  await page.unroute(SWEEP);
  await page.route(SWEEP, answerSweep);
  await gotoOnion(page, conductorUrl(lang, sweep));
  await shows(page, sweep);
}

async function tabTo(page, selector) {
  for (let step = 0; step < 40; step += 1) {
    await page.keyboard.press("Tab");
    if (await page.evaluate((sel) => document.activeElement.matches(sel), selector)) return;
  }
  throw new Error(`no focus stop matches ${selector}`);
}

/**
 * Args:
 *   name: view name.
 *   lang: language code of the conductor.
 *   sweep: forced sweep state.
 *   then: brings the shown conductor into the state to capture.
 */
function view(name, lang, sweep, then) {
  return {
    name,
    url: conductorUrl(lang, sweep),
    prepare: async (page) => {
      await openConductor(page, lang, sweep);
      if (then) await then(page);
    },
  };
}

exports.register = function () {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openConductor(page, "en", "done");
    await assertDesignTokens(page, "logout");
  });

  test("design: page, table, alert and dividers take the tokens in both modes", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openConductor(page, "en", "done");
    expect(
      await page.locator("table.table").evaluate((table) => getComputedStyle(table).getPropertyValue("--bs-table-accent-bg")),
      "logout: the page's own Bootstrap stylesheet must be loaded",
    ).not.toBe("");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      const label = `logout ${mode}`;
      await assertToken(page, "body", "background-color", "--design-surface-1", label);
      await assertToken(page, HEADING, "color", "--design-text", label);
      await assertToken(page, BODY_CELL, "background-color", "--design-surface-2", label);
      await assertToken(page, BODY_CELL, "color", "--design-text", label);
      await assertToken(page, HEAD_CELL, "background-color", "--design-surface-3", label);
      await assertToken(page, HEAD_CELL, "color", "--design-text", label);
      await assertToken(page, "tbody tr", "border-bottom-color", "--design-border", label);
      await assertToken(page, BODY_CELL, "border-right-color", "--design-border", label);
      await assertToken(page, "thead tr", "border-bottom-color", "--design-border", label);
      await assertToken(page, SERVICE_LINK, "color", "--design-link", label);
      await assertToken(page, WARNING, "color", "--design-warning", label);
      await assertToken(page, WARNING, "background-color", "--design-warning-subtle", label);
      await assertToken(page, WARNING, "border-top-color", "--design-warning-border", label);
      const stripe = await tokenValue(page, "--design-surface-3", "color");
      expect(
        await page.locator(BODY_CELL).first().evaluate((cell) => getComputedStyle(cell).boxShadow),
        `${label}: the striped row must be drawn in --design-surface-3`,
      ).toContain(stripe);
    }
    await page.emulateMedia({ colorScheme: null });
  });

  for (const [sweep, marker, token] of [
    ["done", DONE, "--design-success"],
    ["failed", FAILED, "--design-danger"],
    ["pending", PENDING, "--design-warning"],
  ]) {
    test(`design: a ${sweep} sweep row takes ${token} in both modes`, async ({ page }) => {
      skipUnlessServiceEnabled("design");
      await openConductor(page, "en", sweep);
      for (const mode of MODES) {
        await page.emulateMedia({ colorScheme: mode });
        await assertToken(page, marker, "color", token, `logout ${sweep} ${mode}`);
      }
      await page.emulateMedia({ colorScheme: null });
      await assertReadable(page, [marker], `logout ${sweep}`);
    });
  }

  test("design: the manual logout control is outlined at rest, filled on hover and ringed on keyboard focus", async ({
    page,
  }) => {
    skipUnlessServiceEnabled("design");
    await openConductor(page, "en", "done");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      const label = `logout manual control ${mode}`;
      await page.mouse.move(0, 0);
      await assertToken(page, MANUAL, "color", "--design-link", label);
      await assertToken(page, MANUAL, "border-top-color", "--design-link", label);
      await page.locator(MANUAL).first().hover({ timeout: resolveTimeout(READY_MS) });
      await assertToken(page, MANUAL, "background-color", "--design-primary", label);
      await assertToken(page, MANUAL, "color", "--design-on-primary", label);
    }
    await page.mouse.move(0, 0);
    await tabTo(page, MANUAL);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      const label = `logout focused manual control ${mode}`;
      await assertToken(page, `${MANUAL}:focus-visible`, "background-color", "--design-primary", label);
      await assertToken(page, `${MANUAL}:focus-visible`, "color", "--design-on-primary", label);
      await assertToken(page, `${MANUAL}:focus-visible`, "box-shadow", "--design-focus-ring", label);
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: a focused plain link draws its outline in the link color", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openConductor(page, "en", "done");
    await tabTo(page, SERVICE_LINK);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, `${SERVICE_LINK}:focus-visible`, "outline-color", "--design-link", `logout ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: the conductor follows the color mode and stays readable", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openConductor(page, "en", "done");
    await assertLightAndDark(page, BODY_CELL, "logout");
    await assertLightAndDark(page, "body", "logout page");
    await assertReadable(
      page,
      [HEADING, "p.lead", WARNING, HEAD_CELL, SERVICE_LINK, STATUS, MANUAL, SOURCE_LINK],
      "logout",
    );
  });

  test("design: the page renders right to left in Arabic and keeps the tokens", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openConductor(page, "ar", "done");
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    await assertToken(page, "body", "background-color", "--design-surface-1", "logout rtl");
    await assertReadable(page, [HEADING, HEAD_CELL, STATUS], "logout rtl");
  });

  test("design: favicon and title are the configured ones and the page shows no logo of its own", async ({
    page,
  }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!designFaviconUrl() || !designTitle(), "logo or title replacement is switched off");
    await openConductor(page, "en", "done");
    await expect.poll(() => page.title()).toContain(designTitle());
    await expect
      .poll(() => page.evaluate(() => document.querySelector("link[rel~='icon']").href))
      .toBe(designFaviconUrl());
    expect(
      (await apiGetOnion(page.request, designFaviconUrl())).status(),
      "logout: the configured favicon must be served",
    ).toBe(200);
    await expect(
      page.locator("body img, body svg"),
      "logout: upstream renders no logo; a new image needs a slot in the design entry",
    ).toHaveCount(0);
  });

  test("design: the conductor loads without a blocked style or script", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const blocked = [];
    page.on("console", (message) => {
      if (/content security policy|refused to (apply|load|execute)/i.test(message.text())) {
        blocked.push(message.text().slice(0, 200));
      }
    });
    await openConductor(page, "en", "done");
    expect(blocked, "logout: no style or script may be blocked").toEqual([]);
  });

  test("design: gallery of the logout conductor", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(900_000));
    await captureDesignGallery(page, galleryViews());
    await page.unroute(SWEEP);
  });
};

function framedView() {
  return {
    name: "framed",
    url: `${base()}/logout`,
    prepare: async (page) => {
      await page.unroute(SWEEP);
      await page.route(SWEEP, answerSweep);
      await page.evaluate((src) => {
        const frame = document.createElement("iframe");
        frame.src = src;
        frame.style.cssText = "position:fixed;inset:0;width:100%;height:100%;border:0";
        document.body.replaceChildren(frame);
      }, conductorUrl("en", "done"));
      await expect.poll(() => page.frames().length, { timeout: resolveTimeout(READY_MS) }).toBe(2);
      const frame = page.frames().find((candidate) => candidate !== page.mainFrame());
      await shows(frame, "done");
      await expect(frame.locator(WARNING), "logout: a framed conductor hides its warning").toBeHidden();
    },
  };
}

function galleryViews() {
  const hover = (selector) => (page) => page.locator(selector).first().hover({ timeout: resolveTimeout(READY_MS) });
  const scrollEnd = (page) =>
    page.locator(".table-responsive").evaluate((box) => box.scrollTo({ left: box.scrollWidth }));
  return [
    view("signed-out", "en", "done"),
    view("signing-out", "en", "pending"),
    view("failed", "en", "failed"),
    view("mixed", "en", "mixed"),
    framedView(),
    view("manual-hover", "en", "done", hover(MANUAL)),
    view("manual-focus", "en", "done", (page) => tabTo(page, MANUAL)),
    view("service-link-hover", "en", "done", hover(SERVICE_LINK)),
    view("service-link-focus", "en", "done", (page) => tabTo(page, SERVICE_LINK)),
    view("source-link-hover", "en", "done", hover(SOURCE_LINK)),
    view("source-link-focus", "en", "done", (page) => tabTo(page, SOURCE_LINK)),
    view("failed-manual-hover", "en", "failed", hover(MANUAL)),
    view("table-scrolled-end", "en", "mixed", scrollEnd),
    view("german", "de", "done"),
    view("german-failed", "de", "failed"),
    view("arabic-rtl", "ar", "done"),
    view("arabic-rtl-signing-out", "ar", "pending"),
    view("persian-rtl-failed", "fa", "failed"),
    view("urdu-rtl-mixed", "ur", "mixed"),
    view("japanese", "ja", "done"),
    view("chinese-signing-out", "zh", "pending"),
    view("hindi", "hi", "done"),
    view("russian-failed", "ru", "failed"),
    view("tamil-long-labels", "ta", "done"),
  ];
}
