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
const { apiGetOnion, decodeDotenvQuotedValue, gotoOnion, performKeycloakLoginForm } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const MODES = ["light", "dark"];
const NAV_COLLAPSED_BELOW = 993;
const INPUT = "#textarea1";
const OUTPUT = "#textarea2";
const CARD_LINK = "#app .card .card-action a";
const CODE = ".code-box pre.code";
const SWAGGER = "#swagger-ui";
const TAG = `${SWAGGER} .opblock-tag`;
const EXECUTE = `${SWAGGER} .btn.execute`;
const RESPONSE_CODE = `${SWAGGER} .live-responses-table .microlight`;
const HELD_ROUTES = ["**/translate", "**/detect", "**/frontend/settings"];
const HOLD_MS = 8_000;
const TRADEMARK_TEXT =
  "This website might be in violation of our trademark guidelines: https://github.com/LibreTranslate/LibreTranslate/blob/main/TRADEMARK.md";
const SHORT = "The quick brown fox jumps over the lazy dog.";
const GERMAN = "Der schnelle braune Fuchs springt über den faulen Hund.";
const LONG = Array.from(
  { length: 4 },
  () => `${SHORT} A translation service keeps every text on its own server.`,
).join("\n\n");
const TRANSLATION = { alternatives: ["Der flinke braune Fuchs springt über den trägen Hund."], translatedText: GERMAN };
const DETECTION = {
  alternatives: [],
  detectedLanguage: { confidence: 97, language: "de" },
  translatedText: SHORT,
};
const DETECTED = [{ confidence: 97, language: "en" }];
const MISSING_TEXT = { error: "Invalid request: missing q parameter" };
const LANGUAGES = [
  { code: "en", name: "English", targets: ["de", "en"] },
  { code: "de", name: "German", targets: ["de", "en"] },
];
const MODELS_ARROW = `${SWAGGER} section.models h4 svg`;
const DOCS_LOGO = `${SWAGGER} .topbar a.link img`;
const DOCS_LOGO_WIDTH_AT_390 = 131;
const DOCS_LOGO_TOLERANCE = 12;
const EMPTY_FORM = "/?lang=en&source=en&target=de";

function base() {
  return decodeDotenvQuotedValue(process.env.LIBRETRANSLATE_BASE_URL).replace(/\/$/, "");
}

function designTitle() {
  return decodeDotenvQuotedValue(process.env.DESIGN_TITLE);
}

function designLogoUrl() {
  return decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL);
}

function designFaviconUrl() {
  return decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL);
}

async function fresh(page) {
  await page.addInitScript(() => {
    try {
      window.localStorage.removeItem("scheme");
    } catch (error) {
      void error;
    }
  });
}

/**
 * Args:
 *   page: Playwright page.
 *   path: route below the base URL, with its query string.
 */
async function visit(page, path) {
  await gotoOnion(page, `${base()}${path}`);
  if (page.url().includes("openid-connect/auth")) {
    await performKeycloakLoginForm(
      page,
      decodeDotenvQuotedValue(process.env.ADMIN_USERNAME),
      decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD),
    );
    await expect.poll(() => page.url(), { timeout: resolveTimeout(60_000) }).toContain(base());
    await gotoOnion(page, `${base()}${path}`);
  }
}

async function loaded(page) {
  await page.waitForFunction(() => window._vueApp && window._vueApp.loading === false, null, {
    timeout: resolveTimeout(60_000),
  });
}

async function appReady(page) {
  await loaded(page);
  if (await page.evaluate(() => window._vueApp.error !== "")) {
    await page.locator(CARD_LINK).click({ timeout: resolveTimeout(10_000) });
  }
  await page.locator(INPUT).waitFor({ state: "visible", timeout: resolveTimeout(20_000) });
}

async function openApp(page, path = "/?lang=en") {
  await visit(page, path);
  await appReady(page);
}

/**
 * Args:
 *   page: Playwright page that shows the translation form.
 *   text: text typed into the source field.
 *   answer: body the browser returns for /translate.
 */
async function translate(page, text, answer = TRANSLATION) {
  await page.unroute("**/translate");
  // The backend loses gunicorn workers to its memory limit while a model loads and answers 502, so the browser answers /translate itself.
  await page.route("**/translate", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(answer) }),
  );
  await page.locator(INPUT).fill(text);
  await page.waitForFunction(
    () => window._vueApp.loadingTranslation === false && window._vueApp.translatedText !== "",
    null,
    { timeout: resolveTimeout(30_000) },
  );
}

async function showCard(page, text) {
  await loaded(page);
  await page.evaluate((message) => {
    if (window._vueApp.error === "") window._vueApp.error = message;
  }, text);
  await page.locator(CARD_LINK).waitFor({ state: "visible", timeout: resolveTimeout(10_000) });
}

function collapsed(page) {
  return page.viewportSize().width < NAV_COLLAPSED_BELOW;
}

async function openNavigation(page) {
  if (!collapsed(page)) return;
  await page.locator("button.sidenav-trigger").click({ timeout: resolveTimeout(10_000) });
  await page.waitForFunction(
    () => {
      const panel = document.querySelector("#nav-mobile");
      return panel.getBoundingClientRect().left === 0 && panel.getAnimations().length === 0;
    },
    null,
    { timeout: resolveTimeout(10_000) },
  );
}

async function closeNavigation(page) {
  if (!collapsed(page)) return;
  await page.locator(".sidenav-overlay").click({ position: { x: 370, y: 400 }, timeout: resolveTimeout(10_000) });
  await page.waitForFunction(() => document.querySelector("#nav-mobile").getBoundingClientRect().right <= 0, null, {
    timeout: resolveTimeout(10_000),
  });
}

async function storedScheme(page) {
  return page.evaluate(() => window.localStorage.getItem("scheme"));
}

async function effectiveScheme(page) {
  return page.evaluate(
    () =>
      window.localStorage.getItem("scheme") ||
      (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"),
  );
}

async function pickScheme(page, target) {
  if ((await effectiveScheme(page)) === target) return;
  await openNavigation(page);
  await page.locator(".change-theme a:visible").first().click({ timeout: resolveTimeout(10_000) });
  await expect.poll(() => effectiveScheme(page), { timeout: resolveTimeout(10_000) }).toBe(target);
  await closeNavigation(page);
}

async function hold(page, pattern) {
  await page.route(pattern, (route) => {
    setTimeout(() => route.continue().catch(() => {}), HOLD_MS);
  });
}

async function release(page) {
  for (const pattern of HELD_ROUTES) await page.unroute(pattern);
}

async function docsReady(page) {
  await page.locator(TAG).first().waitFor({ state: "visible", timeout: resolveTimeout(180_000) });
}

async function openDocs(page) {
  await visit(page, "/docs/");
  await docsReady(page);
}

async function expandOperation(page, method) {
  const block = page.locator(`${SWAGGER} .opblock.opblock-${method}`).first();
  await block.locator(".opblock-summary").click({ timeout: resolveTimeout(10_000) });
  await block.locator(".opblock-body").waitFor({ state: "visible", timeout: resolveTimeout(10_000) });
  return block;
}

async function tryOut(page, method) {
  const block = await expandOperation(page, method);
  await block.locator(".try-out__btn").click({ timeout: resolveTimeout(10_000) });
  await block.locator(".btn.execute").waitFor({ state: "visible", timeout: resolveTimeout(10_000) });
  return block;
}

async function execute(page, method) {
  const block = await tryOut(page, method);
  await block.locator(".btn.execute").click({ timeout: resolveTimeout(10_000) });
  await block.locator(".live-responses-table").waitFor({ state: "visible", timeout: resolveTimeout(60_000) });
  return block;
}

function appView(name, path, prepare) {
  return {
    name,
    url: `${base()}${path}`,
    prepare: async (page) => {
      await release(page);
      await appReady(page);
      if (prepare) await prepare(page);
    },
  };
}

function rawView(name, path, prepare) {
  return {
    name,
    url: `${base()}${path}`,
    prepare: async (page) => {
      await release(page);
      await prepare(page);
    },
  };
}

function docsView(name, prepare) {
  return rawView(name, "/docs/", async (page) => {
    await docsReady(page);
    if (prepare) await prepare(page);
  });
}

exports.register = function () {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await fresh(page);
    await openApp(page);
    await assertDesignTokens(page, "libretranslate");
    await openDocs(page);
    await assertDesignTokens(page, "libretranslate docs");
  });

  test("design: page, fields, frame, code and dividers take the tokens in both modes", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await fresh(page);
    await openApp(page, EMPTY_FORM);
    await translate(page, SHORT);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      const label = `libretranslate ${mode}`;
      await assertToken(page, "body", "background-color", "--design-surface-1", label);
      await assertToken(page, "h3.header", "color", "--design-text", label);
      await assertToken(page, INPUT, "background-color", "--design-surface-2", label);
      await assertToken(page, INPUT, "color", "--design-text", label);
      await assertToken(page, OUTPUT, "border-top-color", "--design-border-strong", label);
      await assertToken(page, CODE, "background-color", "--design-surface-2", label);
      await assertToken(page, CODE, "border-top-color", "--design-border", label);
      await assertToken(page, "nav", "background-color", "--design-frame", label);
      await assertToken(page, "footer.page-footer", "background-color", "--design-frame", label);
      await assertToken(page, "footer.page-footer h5", "color", "--design-on-frame", label);
      await assertToken(page, "footer.page-footer p a", "color", "--design-on-frame", label);
      await assertToken(page, ".btn-copy-translated", "color", "--design-text-muted", label);
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: the error card takes the tokens", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await fresh(page);
    await visit(page, "/?lang=en");
    await showCard(page, TRADEMARK_TEXT);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      const label = `libretranslate card ${mode}`;
      await assertToken(page, "#app .card .card-content", "background-color", "--design-surface-2", label);
      await assertToken(page, CARD_LINK, "color", "--design-link", label);
      await assertToken(page, "#app .card .card-action", "border-top-color", "--design-border", label);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, ["#app .card .card-content p", CARD_LINK], "libretranslate card");
  });

  test("design: the translator stays readable in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await fresh(page);
    await openApp(page, EMPTY_FORM);
    await translate(page, SHORT);
    await assertLightAndDark(page, INPUT, "libretranslate translator");
    await assertReadable(
      page,
      [
        "h3.header",
        INPUT,
        OUTPUT,
        ".language-select select",
        ".btn-copy-translated",
        ".code-box p",
        `${CODE} code`,
        `${CODE} .token.string`,
        `${CODE} .token.punctuation`,
        { selector: `${CODE} .token.keyword`, optional: true },
        { selector: "#sourceLangLabel", optional: true },
        { selector: "#nav li a", optional: true },
        "footer.page-footer h5",
        "footer.page-footer .footer-copyright p",
      ],
      "libretranslate translator",
    );
  });

  test("design: the API documentation takes the tokens and its primary action is readable", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await fresh(page);
    await openDocs(page);
    await page.route("**/languages", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(LANGUAGES) }),
    );
    await execute(page, "get");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      const label = `libretranslate docs ${mode}`;
      await assertToken(page, "body", "background-color", "--design-surface-1", label);
      await assertToken(page, `${SWAGGER} .info .title`, "color", "--design-text", label);
      await assertToken(page, `${SWAGGER} .topbar`, "background-color", "--design-frame", label);
      await assertToken(page, EXECUTE, "background-color", "--design-primary", label);
      await assertToken(page, EXECUTE, "color", "--design-on-primary", label);
      await assertToken(page, TAG, "border-bottom-color", "--design-border", label);
      await assertToken(page, RESPONSE_CODE, "background-color", "--design-surface-3", label);
      await assertToken(page, RESPONSE_CODE, "color", "--design-text", label);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, `${SWAGGER} .info`, "libretranslate docs");
    await assertReadable(
      page,
      [
        `${SWAGGER} .info .title`,
        `${SWAGGER} .info .title small pre`,
        TAG,
        `${SWAGGER} .opblock-summary-path`,
        `${SWAGGER} .opblock-post .opblock-summary-method`,
        `${SWAGGER} .opblock-get .opblock-summary-method`,
        `${SWAGGER} .opblock-section-header h4`,
        `${SWAGGER} .btn.try-out__btn`,
        `${SWAGGER} .topbar .download-url-button`,
        EXECUTE,
        RESPONSE_CODE,
        `${RESPONSE_CODE} span[style]`,
      ],
      "libretranslate docs",
    );
  });

  test("design: the collapse arrow of the models header takes the text token in both modes", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await fresh(page);
    await openDocs(page);
    await page.locator(MODELS_ARROW).first().scrollIntoViewIfNeeded({ timeout: resolveTimeout(10_000) });
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, MODELS_ARROW, "fill", "--design-text", `libretranslate docs models ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, `${SWAGGER} section.models h4`, "libretranslate docs models");
  });

  test("design: the lockup keeps its width in the top bar of the API documentation at 390 px", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!designLogoUrl(), "logo replacement is switched off");
    await fresh(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await openDocs(page);
    const box = await page.locator(DOCS_LOGO).boundingBox();
    expect(
      box.width,
      `libretranslate docs: the lockup must keep ${DOCS_LOGO_WIDTH_AT_390} px at a 390 px viewport (tolerance ${DOCS_LOGO_TOLERANCE} px), it is ${box.width} px wide`,
    ).toBeGreaterThanOrEqual(DOCS_LOGO_WIDTH_AT_390 - DOCS_LOGO_TOLERANCE);
  });

  test("design: the API documentation loads without a blocked request", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const own = [new URL(base()).origin, designLogoUrl() ? new URL(designLogoUrl()).origin : ""].filter(Boolean);
    const blocked = [];
    page.on("console", (message) => {
      if (/content security policy|refused to/i.test(message.text())) blocked.push(message.text().slice(0, 200));
    });
    page.on("requestfailed", (request) => {
      if (own.some((origin) => request.url().startsWith(origin))) {
        blocked.push(`${request.url()} ${request.failure() ? request.failure().errorText : ""}`);
      }
    });
    await fresh(page);
    await openDocs(page);
    await expandOperation(page, "post");
    expect(blocked, "libretranslate docs: no request may be blocked").toEqual([]);
  });

  test("design: every image the role stylesheet references is served", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await fresh(page);
    await openApp(page);
    const sheet = await page
      .locator("link[href*='/roles/web-svc-libretranslate/'][href*='style.css']")
      .first()
      .getAttribute("href");
    const css = await (await apiGetOnion(page.request, sheet)).text();
    const targets = [...new Set([...css.matchAll(/url\(\s*["']?([^"')]+)["']?\s*\)/g)].map((match) => match[1]))]
      .filter((target) => !target.startsWith("data:"))
      .map((target) => new URL(target, sheet).href);
    test.skip(targets.length === 0, "the role stylesheet references no image besides data URIs");
    for (const target of targets) {
      const served = await apiGetOnion(page.request, target);
      expect(
        `${served.status()} ${served.headers()["content-type"]}`,
        `${target} must be served as an image; a relative url() resolves against the stylesheet on the CDN`,
      ).toMatch(/^200 image\//);
    }
  });

  test("design: the theme switch drives the tokens", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await fresh(page);
    await page.emulateMedia({ colorScheme: "light" });
    await openApp(page);
    const light = await tokenValue(page, "--design-surface-1", "color");
    await expect(page.locator("html")).not.toHaveAttribute("data-design-theme", /.+/);
    await pickScheme(page, "dark");
    await expect(page.locator("html")).toHaveAttribute("data-design-theme", "dark");
    await expect.poll(() => tokenValue(page, "--design-surface-1", "color")).not.toBe(light);
    await assertToken(page, "body", "background-color", "--design-surface-1", "libretranslate forced dark");
    await assertToken(page, INPUT, "color", "--design-text", "libretranslate forced dark");
    await pickScheme(page, "light");
    await expect.poll(() => storedScheme(page)).toBeNull();
    await expect(page.locator("html")).not.toHaveAttribute("data-design-theme", /.+/);
    await expect.poll(() => tokenValue(page, "--design-surface-1", "color")).toBe(light);
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: a chosen theme also reaches the API documentation", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.emulateMedia({ colorScheme: "light" });
    await openApp(page);
    await pickScheme(page, "dark");
    await openDocs(page);
    await expect(page.locator("html")).toHaveAttribute("data-design-theme", "dark");
    await assertToken(page, "body", "background-color", "--design-surface-1", "libretranslate docs forced dark");
    await page.evaluate(() => window.localStorage.removeItem("scheme"));
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: every focus stop of the navigation bar draws its indicator in the frame text color", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await fresh(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await openApp(page);
    const expected = await page.evaluate(() => {
      const probe = document.createElement("span");
      probe.style.color = "var(--design-on-frame)";
      document.querySelector("nav").appendChild(probe);
      const value = getComputedStyle(probe).color;
      probe.remove();
      return value;
    });
    const stops = await page.locator("#logo-container, #nav a:visible").count();
    expect(stops, "libretranslate: the navigation bar must hold focus stops").toBeGreaterThan(2);
    await page.locator("#logo-container").focus();
    await page.keyboard.press("Tab");
    await page.keyboard.press("Shift+Tab");
    for (let index = 0; index < stops; index += 1) {
      const stop = await page.evaluate(() => {
        const active = document.activeElement;
        const style = getComputedStyle(active);
        return { inside: Boolean(active.closest("nav")), color: style.outlineColor, style: style.outlineStyle };
      });
      expect(stop.inside, `libretranslate: focus stop ${index} must sit inside the navigation bar`).toBe(true);
      expect(stop.style, `libretranslate: focus stop ${index} must draw an outline`).not.toBe("none");
      expect(stop.color, `libretranslate: focus stop ${index} must use --design-on-frame`).toBe(expected);
      await page.keyboard.press("Tab");
    }
  });

  test("design: logo, favicon and title are the configured ones", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!designLogoUrl() || !designTitle(), "logo or title replacement is switched off");
    await fresh(page);
    await openApp(page);
    await expect.poll(() => page.title()).toBe(designTitle());
    await expect(page.locator("h3.header")).toHaveText(designTitle());
    await expect
      .poll(() => page.evaluate(() => document.querySelector("link[rel~='icon']").href))
      .toBe(designFaviconUrl());
    const logo = page.locator("#logo-container img.logo");
    expect(await logo.evaluate((image) => getComputedStyle(image).content)).toContain(designLogoUrl());
    await expect(page.locator("#logo-container span")).toBeHidden();
    const box = await logo.boundingBox();
    expect(box.width, "libretranslate: the logo box must be wider than high").toBeGreaterThan(box.height * 1.5);
    const served = await (await apiGetOnion(page.request, designLogoUrl())).text();
    const onFrame = await page.evaluate(() => {
      const probe = document.createElement("canvas").getContext("2d");
      probe.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--design-on-frame").trim();
      return probe.fillStyle;
    });
    expect(served.toLowerCase(), "libretranslate: the lockup text must use the frame text color").toContain(
      `fill="${onFrame}"`,
    );
    await openDocs(page);
    await expect.poll(() => page.title()).toBe(designTitle());
    await expect
      .poll(() => page.evaluate(() => document.querySelector("link[rel~='icon']").href))
      .toBe(designFaviconUrl());
    const docsLogo = page.locator(`${SWAGGER} .topbar a.link img`);
    expect(await docsLogo.evaluate((image) => getComputedStyle(image).content)).toContain(designLogoUrl());
    const docsBox = await docsLogo.boundingBox();
    expect(docsBox.width, "libretranslate docs: the logo box must be wider than high").toBeGreaterThan(
      docsBox.height * 1.5,
    );
  });

  test("design: the app's theme switch raises no page error and leaves the injected sheets alone", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await fresh(page);
    await page.emulateMedia({ colorScheme: "light" });
    await openApp(page);
    const light = await tokenValue(page, "--design-surface-1", "color");
    await pickScheme(page, "dark");
    await pickScheme(page, "light");
    expect(
      errors,
      "the app walks every stylesheet at load and on a theme change; an injected one must not make it throw",
    ).toEqual([]);
    await page.emulateMedia({ colorScheme: "dark" });
    await expect
      .poll(() => tokenValue(page, "--design-surface-1", "color"), {
        message: "the app rewrote the color-scheme rule of the shared sheet: the tokens no longer follow the system",
      })
      .not.toBe(light);
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: gallery of the translator and the API documentation", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(2_700_000));
    await fresh(page);
    await openApp(page);
    const hover = (selector) => (page) => page.locator(selector).first().hover({ timeout: resolveTimeout(10_000) });
    const scrollTo = (selector) => (page) =>
      page.locator(selector).first().scrollIntoViewIfNeeded({ timeout: resolveTimeout(10_000) });

    await captureDesignGallery(page, [
      appView("start", "/?lang=en"),
      rawView("trademark-card", "/?lang=en", (page) => showCard(page, TRADEMARK_TEXT)),
      rawView("card-dismiss-hover", "/?lang=en", async (page) => {
        await showCard(page, TRADEMARK_TEXT);
        await hover(CARD_LINK)(page);
      }),
      appView("translated", EMPTY_FORM, (page) => translate(page, SHORT)),
      appView("auto-detect", "/?lang=en&source=auto&target=en", (page) => translate(page, GERMAN, DETECTION)),
      appView("long-text", EMPTY_FORM, (page) =>
        translate(page, LONG, { alternatives: [], translatedText: LONG.replaceAll(SHORT, GERMAN) }),
      ),
      appView("code-boxes", EMPTY_FORM, async (page) => {
        await translate(page, SHORT);
        await scrollTo(".code-row-wrapper")(page);
      }),
      appView("input-focus", "/?lang=en", (page) => page.locator(INPUT).focus()),
      appView("source-select-focus", "/?lang=en", async (page) => {
        await page.locator(INPUT).focus();
        await page.keyboard.press("Shift+Tab");
        await page.keyboard.press("Shift+Tab");
        await page.keyboard.press("Shift+Tab");
      }),
      appView("delete-hover", EMPTY_FORM, async (page) => {
        await translate(page, SHORT);
        await hover(".btn-delete-text")(page);
      }),
      appView("copy-hover", EMPTY_FORM, async (page) => {
        await translate(page, SHORT);
        await hover(".btn-copy-translated")(page);
      }),
      appView("translating", EMPTY_FORM, async (page) => {
        await hold(page, "**/translate");
        await page.locator(INPUT).fill(SHORT);
        await page.locator(".progress.translate").waitFor({ state: "visible", timeout: resolveTimeout(10_000) });
      }),
      rawView("loading", "/?lang=en", async (page) => {
        await hold(page, "**/frontend/settings");
        await gotoOnion(page, `${base()}/?lang=en`);
        await page.locator(".preloader-wrapper.active").waitFor({ state: "visible", timeout: resolveTimeout(10_000) });
      }),
      appView("error-request-failed", EMPTY_FORM, async (page) => {
        await page.route("**/translate", (route) => route.abort());
        await page.locator(INPUT).fill(SHORT);
        await page.locator(CARD_LINK).waitFor({ state: "visible", timeout: resolveTimeout(10_000) });
      }),
      appView("navigation", "/?lang=en", async (page) => {
        await openNavigation(page);
        await page.locator(".change-language a:visible").first().click({ timeout: resolveTimeout(10_000) });
        await page.locator("select#locales:visible").waitFor({ state: "visible", timeout: resolveTimeout(10_000) });
      }),
      appView("nav-link-hover", "/?lang=en", async (page) => {
        await openNavigation(page);
        await page.locator("a[href$='/docs']:visible").first().hover({ timeout: resolveTimeout(10_000) });
      }),
      appView("locale-german", "/?lang=de"),
      appView("theme-forced-dark", "/?lang=en", (page) => pickScheme(page, "dark")),
      appView("footer", "/?lang=en", scrollTo("footer.page-footer .footer-copyright")),
      docsView("docs"),
      docsView("docs-operation", async (page) => {
        await expandOperation(page, "post");
      }),
      docsView("docs-try-it-out", async (page) => {
        const block = await tryOut(page, "post");
        await block.locator(".btn.execute").scrollIntoViewIfNeeded({ timeout: resolveTimeout(10_000) });
      }),
      docsView("docs-response", async (page) => {
        const block = await execute(page, "get");
        await block.locator(".live-responses-table").scrollIntoViewIfNeeded({ timeout: resolveTimeout(10_000) });
      }),
      docsView("docs-post-response", async (page) => {
        await page.route("**/detect", (route) =>
          route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(DETECTED) }),
        );
        const block = await execute(page, "post");
        await block.locator(".live-responses-table").scrollIntoViewIfNeeded({ timeout: resolveTimeout(10_000) });
      }),
      docsView("docs-error-response", async (page) => {
        await page.route("**/detect", (route) =>
          route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify(MISSING_TEXT) }),
        );
        const block = await execute(page, "post");
        await block.locator(".live-responses-table").scrollIntoViewIfNeeded({ timeout: resolveTimeout(10_000) });
      }),
      docsView("docs-models", async (page) => {
        const models = page.locator(`${SWAGGER} section.models`);
        await models.scrollIntoViewIfNeeded({ timeout: resolveTimeout(10_000) });
        await models.locator("button.model-box-control").first().click({ timeout: resolveTimeout(10_000) });
        await models.locator(".model-box-control[aria-expanded='true']").first().waitFor({
          state: "visible",
          timeout: resolveTimeout(10_000),
        });
      }),
    ]);
  });
};
