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
const { decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const SETTINGS_KEY = "hugoDocsUserSettings";
const TOGGLE = "#theme-toggle:visible";
const HEADER_LINK = "body > header a.font-semibold";
const DRAWER = "body > div.bg-blue-950";
const SEARCH_INPUT = "[aria-label='Search docs'] input[type='search']";
const SEARCH_RESULT = "[aria-label='Search docs'] ul[role='list'] a";
const SEARCH_HITS = [
  ["Configuration", "Introduction", "Configuration file", "Environment variables", "/configuration/introduction/"],
  ["Configuration", "Configure build", "Options", "cachebusters", "/configuration/build/"],
  ["Functions", "css.TailwindCSS", "Setup", "Options", "/functions/css/tailwindcss/"],
  ["Functions", "strings.Contains", "Usage", "", "/functions/strings/contains/"],
  ["Content management", "URL management", "Aliases", "Permalinks", "/content-management/urls/"],
];

function baseUrl() {
  return decodeDotenvQuotedValue(process.env.APP_BASE_URL).replace(/\/$/, "");
}

function designTitle() {
  return decodeDotenvQuotedValue(process.env.DESIGN_TITLE);
}

function designFaviconUrl() {
  return decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL);
}

function designLogoUrl() {
  return decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL);
}

function designSymbolUrl() {
  return decodeDotenvQuotedValue(process.env.DESIGN_SYMBOL_URL);
}

async function imageSize(page, url) {
  return page.evaluate(
    (source) =>
      new Promise((resolve) => {
        const image = new Image();
        image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight });
        image.onerror = () => resolve({ width: 0, height: 0 });
        image.src = source;
      }),
    url,
  );
}

async function freshSettings(page) {
  await page.addInitScript((key) => {
    try {
      window.localStorage.removeItem(key);
    } catch (error) {
      void error;
    }
  }, SETTINGS_KEY);
}

async function stubSearch(page) {
  await page.addInitScript((rows) => {
    const original = window.fetch.bind(window);
    window.fetch = (input, init) => {
      const url = typeof input === "string" ? input : input.url;
      if (!/algolia\.net\//.test(url)) return original(input, init);
      const hits = rows.map(([lvl0, lvl1, lvl2, lvl3, path], index) => ({
        objectID: `fixture-${index}`,
        url: path,
        hierarchy: { lvl0, lvl1, lvl2, lvl3 },
        _highlightResult: {
          hierarchy: { lvl2: { value: lvl2 }, lvl3: lvl3 ? { value: lvl3 } : undefined },
        },
        _snippetResult: { content: { value: `Fixture result for ${lvl1}` } },
      }));
      return Promise.resolve(
        new Response(JSON.stringify({ results: [{ hits }] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    };
  }, SEARCH_HITS);
}

async function ready(page, selector) {
  await page.locator(selector).first().waitFor({ state: "visible", timeout: resolveTimeout(20_000) });
  await page.waitForFunction(() => document.querySelectorAll("[x-cloak]").length === 0, null, {
    timeout: resolveTimeout(20_000),
  });
}

async function open(page, path, selector) {
  await gotoOnion(page, `${baseUrl()}${path}`);
  await ready(page, selector);
}

async function quiet(page) {
  await page.waitForFunction(() => document.getAnimations().every((a) => a.playState !== "running"), null, {
    timeout: resolveTimeout(10_000),
  });
}

async function darkClass(page) {
  return page.evaluate(() => document.documentElement.classList.contains("dark"));
}

async function pickScheme(page, clicks) {
  const toggle = page.locator(TOGGLE).first();
  for (let count = 0; count < clicks; count += 1) {
    await toggle.click({ timeout: resolveTimeout(10_000) });
  }
}

async function openSearch(page) {
  await page.locator("body > header button[aria-label='Search']").first().click({ timeout: resolveTimeout(10_000) });
  await page.locator(SEARCH_INPUT).waitFor({ state: "visible", timeout: resolveTimeout(10_000) });
  await quiet(page);
}

async function searchFor(page, query) {
  await openSearch(page);
  await page.locator(SEARCH_INPUT).fill(query);
  await page.locator(SEARCH_RESULT).first().waitFor({ state: "visible", timeout: resolveTimeout(10_000) });
}

async function openDrawer(page) {
  await page.locator("button[aria-label='Open menu']").click({ timeout: resolveTimeout(10_000) });
  await page.locator(`${DRAWER} nav a`).first().waitFor({ state: "visible", timeout: resolveTimeout(10_000) });
  await quiet(page);
}

async function narrow(page) {
  return page.viewportSize().width < 640;
}

async function assertHeaderFocus(page) {
  const expected = await tokenValue(page, "--design-on-frame", "color");
  const seen = [];
  for (let step = 0; step < 14; step += 1) {
    await page.keyboard.press("Tab");
    const stop = await page.evaluate(() => {
      const element = document.activeElement;
      if (!element || !element.closest("body > header") || element.closest("[role='dialog']")) return null;
      const style = getComputedStyle(element);
      return {
        label: element.getAttribute("aria-label") || element.textContent.trim(),
        color: style.outlineColor,
        style: style.outlineStyle,
        width: style.outlineWidth,
      };
    });
    if (stop) seen.push(stop);
  }
  expect(
    seen.map((stop) => stop.label),
    "hugo: the search button and the theme toggle must be among the focus stops of the header",
  ).toEqual(expect.arrayContaining(["Search", "Toggle color scheme"]));
  for (const stop of seen) {
    expect(stop.style, `hugo: focus outline style of '${stop.label}'`).toBe("solid");
    expect(stop.color, `hugo: focus outline color of '${stop.label}'`).toBe(expected);
    expect(parseFloat(stop.width), `hugo: focus outline width of '${stop.label}'`).toBeGreaterThanOrEqual(2);
  }
}

async function assertScrolledHeader(page) {
  await page.locator("body > footer").scrollIntoViewIfNeeded({ timeout: resolveTimeout(10_000) });
  await expect(page.locator("body > header")).toHaveClass(/bg-blue-950\/80/);
  await assertToken(page, "body > header", "background-color", "--design-frame", "hugo scrolled header");
}

async function assertWordmark(page) {
  const brand = page.locator("body > header > div:first-child > a");
  const wordmark = await brand.evaluate((link) => {
    const text = getComputedStyle(link, "::after");
    return { symbol: getComputedStyle(link).backgroundImage, content: text.content, color: text.color };
  });
  expect(wordmark.symbol, "hugo: the header brand shows the symbol").toContain(designSymbolUrl());
  expect(wordmark.content, "hugo: the header brand spells the design title").toBe(JSON.stringify(designTitle()));
  expect(wordmark.color, "hugo: the header wordmark takes the frame text tone").toBe(
    await tokenValue(page, "--design-on-frame", "color"),
  );
  const box = await brand.boundingBox();
  expect(box.width, "hugo: the header brand box must be wider than high").toBeGreaterThan(box.height * 1.5);
}

function at(selector, then) {
  return async (page) => {
    await ready(page, selector);
    if (then) await then(page);
  };
}

function scrollTo(selector) {
  return (page) => page.locator(selector).first().scrollIntoViewIfNeeded({ timeout: resolveTimeout(10_000) });
}

exports.register = function () {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await freshSettings(page);
    await open(page, "/", "img[alt='Hugo Logo']");
    await assertDesignTokens(page, "hugo");
  });

  test("design: page, text, primary action and frame take the tokens in both modes", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await freshSettings(page);
    await open(page, "/", "img[alt='Hugo Logo']");
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      await expect.poll(() => darkClass(page)).toBe(mode === "dark");
      await assertToken(page, "body", "background-color", "--design-surface-1", `hugo ${mode}`);
      await assertToken(page, "body", "color", "--design-text", `hugo ${mode}`);
      await assertToken(page, "a.bg-blue-600", "background-color", "--design-primary", `hugo ${mode}`);
      await assertToken(page, "a.bg-blue-600", "color", "--design-on-primary", `hugo ${mode}`);
      await assertToken(page, "div.bg-blue-600", "fill", "--design-on-primary", `hugo ${mode}`);
      await assertToken(page, "body > header", "background-color", "--design-frame", `hugo ${mode}`);
      await assertToken(page, HEADER_LINK, "color", "--design-on-frame", `hugo ${mode}`);
      await assertToken(page, "body > footer", "background-color", "--design-frame", `hugo ${mode}`);
      await assertToken(page, "body > footer a", "color", "--design-on-frame", `hugo ${mode}`);
      await assertToken(page, "main hr", "border-top-color", "--design-border", `hugo ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: article content stays readable in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await freshSettings(page);
    await open(page, "/contribute/documentation/", "#article h1");
    await assertLightAndDark(page, "main", "hugo article");
    await assertReadable(
      page,
      [
        "#article h1",
        "#article .content p",
        "#article .content p a",
        "#article .content h2",
        "#article .content code",
        "#article .content th",
        "#article .content td",
        "nav[aria-label='breadcrumb'] a",
        ".border-l-4.bg-blue-50 p",
        ".border-l-4.bg-green-50 p",
        ".border-l-4.bg-orange-50 p",
        ".border-l-4.bg-red-50 p",
        ".render-hook-codeblock > .san-serif",
        ".highlight .chroma .cl",
        "aside a",
        "aside h2",
        HEADER_LINK,
        "body > header a[aria-label='Star on GitHub']",
        "body > footer a",
      ],
      "hugo article",
    );
    await open(page, "/content-management/urls/", "#article h1");
    await assertReadable(
      page,
      [
        ".shortcode-code nav button",
        ".shortcode-code nav button.bg-light",
        ".shortcode-code [aria-label='Filename']",
        "span.bg-green-200 a",
        "span.bg-orange-200 a",
        ".shortcode-code [x-ref='toml'] .chroma .nx",
        ".shortcode-code [x-ref='toml'] .chroma .s1",
        ".shortcode-code [x-ref='toml'] .chroma .c",
        ".shortcode-code [x-ref='toml'] .chroma .p",
      ],
      "hugo front matter",
    );
  });

  test("design: alerts take the status tokens in both modes", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await freshSettings(page);
    await open(page, "/contribute/documentation/", "#article h1");
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      await expect.poll(() => darkClass(page)).toBe(mode === "dark");
      for (const [upstream, status] of [
        ["blue", "info"],
        ["green", "success"],
        ["orange", "warning"],
        ["red", "danger"],
      ]) {
        const alert = `.border-l-4.bg-${upstream}-50`;
        await assertToken(page, alert, "background-color", `--design-${status}-subtle`, `hugo ${mode}`);
        await assertToken(page, alert, "border-top-color", `--design-${status}-border`, `hugo ${mode}`);
        await assertToken(page, `${alert} svg`, "fill", `--design-${status}`, `hugo ${mode}`);
      }
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: list cards, dividers and code panels follow the tokens in both modes", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await freshSettings(page);
    await open(page, "/getting-started/", "article a.a--block");
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      await expect.poll(() => darkClass(page)).toBe(mode === "dark");
      await assertToken(page, "article a.a--block", "border-top-color", "--design-border", `hugo list ${mode}`);
      await assertToken(page, "article a.a--block .text-primary", "color", "--design-link", `hugo list ${mode}`);
    }
    await open(page, "/quick-reference/emojis/", "#article table");
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      await expect.poll(() => darkClass(page)).toBe(mode === "dark");
      await assertToken(page, "#article tbody tr", "border-bottom-color", "--design-border", `hugo table ${mode}`);
      await assertToken(page, "#article table", "border-top-color", "--design-border", `hugo table ${mode}`);
      await assertToken(page, "#article th", "background-color", "--design-surface-3", `hugo table ${mode}`);
      await assertToken(page, "#article th", "color", "--design-text", `hugo table ${mode}`);
    }
    await open(page, "/getting-started/quick-start/", "#article h1");
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      await expect.poll(() => darkClass(page)).toBe(mode === "dark");
      await assertToken(page, ".render-hook-codeblock", "background-color", "--design-surface-2", `hugo code ${mode}`);
      await assertToken(page, ".render-hook-codeblock", "border-top-color", "--design-border", `hugo code ${mode}`);
      await assertToken(page, ".highlight .chroma", "background-color", "--design-surface-2", `hugo code ${mode}`);
      await assertToken(page, ".highlight .chroma", "color", "--design-text", `hugo code ${mode}`);
      await assertToken(page, "a.bg-blue-600.not-prose", "color", "--design-on-primary", `hugo improve ${mode}`);
      await assertToken(page, "a.bg-blue-600.not-prose", "background-color", "--design-primary", `hugo improve ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: the theme switch drives the tokens", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await freshSettings(page);
    await page.emulateMedia({ colorScheme: "light" });
    await open(page, "/", TOGGLE);
    const light = await tokenValue(page, "--design-surface-1", "color");
    await expect(page.locator("html")).not.toHaveAttribute("data-design-theme", /.+/);
    await pickScheme(page, 2);
    await expect(page.locator("html")).toHaveClass(/(^|\s)dark(\s|$)/);
    await expect(page.locator("html")).toHaveAttribute("data-design-theme", "dark");
    await expect.poll(() => tokenValue(page, "--design-surface-1", "color")).not.toBe(light);
    await assertToken(page, "body", "background-color", "--design-surface-1", "hugo forced dark");
    await assertToken(page, "body", "color", "--design-text", "hugo forced dark");
    await assertToken(page, TOGGLE, "background-color", "--design-primary-hover", "hugo hovered theme toggle");
    await assertToken(page, TOGGLE, "color", "--design-on-primary", "hugo hovered theme toggle");
    await page.mouse.move(0, 0);
    await assertToken(page, TOGGLE, "background-color", "--design-primary", "hugo theme toggle");
    await assertToken(page, TOGGLE, "color", "--design-on-primary", "hugo theme toggle");
    await pickScheme(page, 1);
    await expect(page.locator("html")).not.toHaveAttribute("data-design-theme", /.+/);
    await page.emulateMedia({ colorScheme: "dark" });
    await expect.poll(() => darkClass(page)).toBe(true);
    await pickScheme(page, 1);
    await expect(page.locator("html")).toHaveAttribute("data-design-theme", "light");
    await expect.poll(() => tokenValue(page, "--design-surface-1", "color")).toBe(light);
    await assertToken(page, "body", "background-color", "--design-surface-1", "hugo forced light");
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: every focus stop inside the header draws its indicator in the frame text tone", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await freshSettings(page);
    await open(page, "/", TOGGLE);
    await assertHeaderFocus(page);
  });

  test("design: the scrolled header stays an opaque frame", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await freshSettings(page);
    await open(page, "/", TOGGLE);
    await assertScrolledHeader(page);
  });

  test("design: logo, favicon and title are the configured ones", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!designLogoUrl() || !designTitle(), "logo or title replacement is switched off");
    await freshSettings(page);
    await open(page, "/", "img[alt='Hugo Logo']");
    await expect.poll(() => page.title()).toContain(designTitle());
    await expect
      .poll(() => page.evaluate(() => Array.from(document.querySelectorAll("link[rel~='icon']"), (link) => link.href)))
      .toEqual([designFaviconUrl(), designFaviconUrl()]);
    const hero = page.locator("img[alt='Hugo Logo']").first();
    expect(await hero.evaluate((image) => getComputedStyle(image).content)).toContain(designLogoUrl());
    const lockup = await imageSize(page, designLogoUrl());
    expect(lockup.width, "hugo: the hero lockup must load and be wider than high").toBeGreaterThan(lockup.height);
    const symbol = await imageSize(page, designSymbolUrl());
    expect(symbol.width, "hugo: the symbol must load").toBeGreaterThan(0);
    expect((await imageSize(page, designFaviconUrl())).width, "hugo: the favicon must load").toBeGreaterThan(0);

    await assertWordmark(page);

    const footer = page.locator("body > footer img[alt='Hugo Logo']");
    expect(await footer.evaluate((image) => getComputedStyle(image).content)).toContain(designSymbolUrl());
    const footerBox = await footer.boundingBox();
    expect(Math.abs(footerBox.width - footerBox.height), "hugo: the footer symbol sits in a square box").toBeLessThan(1);

    await open(page, "/getting-started/quick-start/", "#article h1");
    await expect.poll(() => page.title()).toContain(designTitle());
  });

  test("design: gallery of the documentation site", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(1_500_000));
    await freshSettings(page);
    await stubSearch(page);
    const base = baseUrl();
    const tab = (name) => `.shortcode-code nav button[aria-label='Toggle ${name}']`;

    await captureDesignGallery(page, [
      { name: "home", url: `${base}/`, prepare: at("img[alt='Hugo Logo']") },
      { name: "home-open-source", url: `${base}/`, prepare: at("img[alt='Hugo Logo']", scrollTo("main dl")) },
      { name: "home-sponsors", url: `${base}/`, prepare: at("img[alt='Hugo Logo']", scrollTo("main h2")) },
      {
        name: "home-features",
        url: `${base}/`,
        prepare: at("img[alt='Hugo Logo']", scrollTo("main .rounded-full.bg-blue-600")),
      },
      { name: "footer", url: `${base}/`, prepare: at("img[alt='Hugo Logo']", scrollTo("body > footer ul")) },
      {
        name: "navigation",
        url: `${base}/`,
        prepare: at(TOGGLE, async (page) => {
          if (await narrow(page)) return openDrawer(page);
          return page.locator(HEADER_LINK).first().hover({ timeout: resolveTimeout(10_000) });
        }),
      },
      {
        name: "navigation-entry-hover",
        url: `${base}/`,
        prepare: at(TOGGLE, async (page) => {
          if (await narrow(page)) {
            await openDrawer(page);
            return page.locator(`${DRAWER} nav a`).nth(1).hover({ timeout: resolveTimeout(10_000) });
          }
          return page.locator("body > header a[aria-label='Star on GitHub']").hover({ timeout: resolveTimeout(10_000) });
        }),
      },
      {
        name: "header-focus",
        url: `${base}/`,
        prepare: at(TOGGLE, async (page) => {
          await page.keyboard.press("Tab");
          await page.keyboard.press("Tab");
        }),
      },
      {
        name: "theme-forced-light",
        url: `${base}/documentation/`,
        prepare: at("article a.a--block", (page) => pickScheme(page, 1)),
      },
      {
        name: "theme-forced-dark",
        url: `${base}/documentation/`,
        prepare: at("article a.a--block", (page) => pickScheme(page, 2)),
      },
      { name: "docs-index", url: `${base}/documentation/`, prepare: at("article a.a--block") },
      {
        name: "docs-card-hover",
        url: `${base}/documentation/`,
        prepare: at("article a.a--block", (page) =>
          page.locator("article a.a--block").first().hover({ timeout: resolveTimeout(10_000) }),
        ),
      },
      { name: "section-list", url: `${base}/getting-started/`, prepare: at("article a.a--block") },
      { name: "functions-list", url: `${base}/functions/strings/`, prepare: at("article a.a--block .font-mono") },
      { name: "news-list", url: `${base}/news/`, prepare: at("article a.a--block") },
      { name: "article", url: `${base}/getting-started/quick-start/`, prepare: at("#article h1") },
      {
        name: "article-code",
        url: `${base}/getting-started/quick-start/`,
        prepare: at("#article h1", scrollTo("#article .highlight")),
      },
      {
        name: "article-page-edit",
        url: `${base}/getting-started/quick-start/`,
        prepare: at("#article h1", scrollTo("a.bg-blue-600.not-prose")),
      },
      {
        name: "article-alerts",
        url: `${base}/contribute/documentation/`,
        prepare: at("#article h1", scrollTo(".border-l-4.bg-orange-50")),
      },
      {
        name: "article-badges",
        url: `${base}/content-management/urls/`,
        prepare: at("#article h1", scrollTo("span.bg-orange-200")),
      },
      {
        name: "article-table",
        url: `${base}/quick-reference/emojis/`,
        prepare: at("#article h1", scrollTo("#article table thead")),
      },
      { name: "glossary", url: `${base}/quick-reference/glossary/`, prepare: at("#article dl dt") },
      { name: "function-page", url: `${base}/functions/strings/contains/`, prepare: at("#article h1") },
      { name: "code-toggle", url: `${base}/configuration/build/`, prepare: at(tab("toml"), scrollTo(tab("toml"))) },
      {
        name: "code-toggle-json",
        url: `${base}/configuration/build/`,
        prepare: at(tab("json"), async (page) => {
          await page.locator(tab("json")).first().click({ timeout: resolveTimeout(10_000) });
          await quiet(page);
        }),
      },
      {
        name: "code-toggle-tab-hover",
        url: `${base}/configuration/build/`,
        prepare: at(tab("yaml"), (page) => page.locator(tab("yaml")).first().hover({ timeout: resolveTimeout(10_000) })),
      },
      { name: "search-open", url: `${base}/`, prepare: at(TOGGLE, openSearch) },
      { name: "search-results", url: `${base}/`, prepare: at(TOGGLE, (page) => searchFor(page, "config")) },
      {
        name: "search-result-hover",
        url: `${base}/`,
        prepare: at(TOGGLE, async (page) => {
          await searchFor(page, "config");
          await page.locator(SEARCH_RESULT).nth(1).hover({ timeout: resolveTimeout(10_000) });
        }),
      },
      { name: "not-found", url: `${base}/404.html`, prepare: at("a.bg-blue-500") },
    ]);
  });
};
