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
const { apiGetOnion, decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const MODES = ["light", "dark"];
const DESKTOP = { width: 1440, height: 900 };
const MOBILE = { width: 390, height: 844 };
const GUTTER = 16;
const AAA = 7;
const FORBIDDEN = 403;
const HEADING = "h1";
const TEXT = [HEADING, "h2", "p", "strong"];
const MAIL_LINK = "a[href^='mailto:']";
const WEB_LINK = "a[href^='http']";
const SERVER_LINE = "center:last-of-type";
const INJECTION_MARK = "infinito-inj";
const SHEETS = ["/_shared/css/layer.css", "/_shared/css/default.css", "/roles/web-svc-html/"];

function base() {
  return normalizeBaseUrl(process.env.APP_BASE_URL || "");
}

function imprintUrl() {
  return decodeDotenvQuotedValue(process.env.IMPRINT_URL || "");
}

function imprintTitle() {
  return decodeDotenvQuotedValue(process.env.IMPRINT_TITLE || "");
}

function skipWithoutImprint() {
  test.skip(!imprintUrl(), "IMPRINT_URL is empty: web-svc-legal is not deployed");
}

async function open(page, url) {
  const response = await gotoOnion(page, url);
  await page.waitForLoadState("load", { timeout: resolveTimeout(30_000) });
  await page.locator("body").waitFor({ state: "visible", timeout: resolveTimeout(20_000) });
  return response;
}

async function assertInjected(page, request, label) {
  const found = await page.evaluate((mark) => {
    const walker = document.createTreeWalker(document, NodeFilter.SHOW_COMMENT);
    let marks = 0;
    while (walker.nextNode()) {
      if (walker.currentNode.data === mark) marks += 1;
    }
    return {
      marks,
      first: document.head.firstElementChild.getAttribute("href") || "",
      sheets: Array.from(document.querySelectorAll("link[rel='stylesheet']"), (link) => link.href),
    };
  }, INJECTION_MARK);
  expect(found.marks, `${label}: the document must carry the injection markers`).toBeGreaterThan(0);
  expect(found.first, `${label}: the layer declaration must be the first element of <head>`).toContain(SHEETS[0]);
  for (const path of SHEETS) {
    const href = found.sheets.find((sheet) => sheet.includes(path));
    expect(href, `${label}: a stylesheet under ${path} must be linked`).toBeTruthy();
    const response = await apiGetOnion(request, href, { timeout: resolveTimeout(30_000) });
    expect(response.status(), `${label}: ${href} must be served`).toBe(200);
    expect(response.headers()["content-type"] || "", `${label}: ${href} must be a stylesheet`).toContain("text/css");
  }
}

async function assertPage(page, label) {
  await assertToken(page, "body", "background-color", "--design-surface-1", label);
  await assertToken(page, "body", "color", "--design-text", label);
  await assertToken(page, "body", "font-family", "--design-font", label);
}

async function textColumn(page) {
  return page.evaluate(() => {
    const root = document.documentElement;
    const boxes = Array.from(document.querySelectorAll("h1, h2, p, a"), (node) => node.getBoundingClientRect());
    return {
      client: root.clientWidth,
      left: Math.min(...boxes.map((box) => box.left)),
      right: Math.max(...boxes.map((box) => box.right)),
      scroll: root.scrollWidth,
    };
  });
}

function views() {
  const error = { name: "error-403", url: `${base()}/` };
  if (!imprintUrl()) return [error];
  const imprint = (name, prepare) => ({
    name,
    url: imprintUrl(),
    prepare: async (page) => {
      await page.locator(HEADING).first().waitFor({ state: "visible", timeout: resolveTimeout(20_000) });
      if (prepare) await prepare(page);
    },
  });
  return [
    imprint("imprint"),
    imprint("imprint-end", (page) => page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))),
    imprint("imprint-link-focus", (page) => page.keyboard.press("Tab")),
    imprint("imprint-link-hover", (page) => page.locator(WEB_LINK).hover({ timeout: resolveTimeout(10_000) })),
    error,
  ];
}

exports.register = function () {
  test.describe("design", () => {
    test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
      skipUnlessServiceEnabled("design");
      await open(page, `${base()}/`);
      await assertDesignTokens(page, "html");
    });

    test("design: the injection reaches the page the proxy answers the root with", async ({ page, request }) => {
      skipUnlessServiceEnabled("design");
      await open(page, `${base()}/`);
      await assertInjected(page, request, "html root");
    });

    test("design: the 403 page of the proxy takes surface, text, font and divider from the tokens", async ({ page }) => {
      skipUnlessServiceEnabled("design");
      const response = await open(page, `${base()}/`);
      test.skip(response.status() !== FORBIDDEN, "an index document replaces the 403 page of the proxy");
      for (const mode of MODES) {
        const label = `html 403 ${mode}`;
        await page.emulateMedia({ colorScheme: mode });
        await assertPage(page, label);
        await assertToken(page, HEADING, "color", "--design-text", label);
        await assertToken(page, "hr", "border-top-color", "--design-border", label);
      }
      await page.emulateMedia({ colorScheme: null });
      await assertLightAndDark(page, "body", "html 403");
      await assertReadable(page, [HEADING, SERVER_LINE], "html 403", AAA);
    });

    test("design: the injection reaches the imprint", async ({ page, request }) => {
      skipUnlessServiceEnabled("design");
      skipWithoutImprint();
      await open(page, imprintUrl());
      await assertInjected(page, request, "html imprint");
    });

    test("design: the imprint takes surface, text, headings and links from the tokens in both modes", async ({ page }) => {
      skipUnlessServiceEnabled("design");
      skipWithoutImprint();
      await open(page, imprintUrl());
      for (const mode of MODES) {
        const label = `html imprint ${mode}`;
        await page.emulateMedia({ colorScheme: mode });
        await assertPage(page, label);
        for (const selector of TEXT) {
          await assertToken(page, selector, "color", "--design-text", label);
        }
        await assertToken(page, MAIL_LINK, "color", "--design-link", label);
        await assertToken(page, WEB_LINK, "color", "--design-link", label);
      }
      await page.emulateMedia({ colorScheme: null });
    });

    test("design: the imprint stays readable in light and dark mode, also on a hovered and a focused link", async ({ page }) => {
      skipUnlessServiceEnabled("design");
      skipWithoutImprint();
      await open(page, imprintUrl());
      await assertLightAndDark(page, "body", "html imprint");
      await assertReadable(page, TEXT, "html imprint text", AAA);
      await assertReadable(page, [MAIL_LINK, WEB_LINK], "html imprint links");
      await page.locator(WEB_LINK).hover({ timeout: resolveTimeout(10_000) });
      for (const mode of MODES) {
        await page.emulateMedia({ colorScheme: mode });
        const resting = await tokenValue(page, "--design-link", "color");
        await expect
          .poll(() => page.locator(WEB_LINK).evaluate((link) => getComputedStyle(link).color), {
            message: `html imprint ${mode}: a hovered link must leave its resting color`,
          })
          .not.toBe(resting);
      }
      await assertReadable(page, [WEB_LINK], "html imprint hovered link");
      await page.keyboard.press("Tab");
      await expect(page.locator(MAIL_LINK)).toBeFocused();
      for (const mode of MODES) {
        const label = `html imprint ${mode}`;
        await page.emulateMedia({ colorScheme: mode });
        await assertToken(page, MAIL_LINK, "outline-color", "--design-link", label);
        await expect
          .poll(() => page.locator(MAIL_LINK).evaluate((link) => getComputedStyle(link).outlineStyle), {
            message: `${label}: a focused link must draw its outline`,
          })
          .toBe("solid");
      }
      await page.emulateMedia({ colorScheme: null });
    });

    test("design: the imprint keeps a gutter at 390 px and a centered text column at 1440 px", async ({ page }) => {
      skipUnlessServiceEnabled("design");
      skipWithoutImprint();
      await page.setViewportSize(MOBILE);
      await open(page, imprintUrl());
      const narrow = await textColumn(page);
      expect(narrow.scroll, "html imprint 390: the page must not scroll sideways").toBeLessThanOrEqual(narrow.client);
      expect(narrow.left, "html imprint 390: the text must keep its left gutter").toBeGreaterThanOrEqual(GUTTER);
      expect(narrow.client - narrow.right, "html imprint 390: the text must keep its right gutter").toBeGreaterThanOrEqual(
        GUTTER,
      );
      await page.setViewportSize(DESKTOP);
      const wide = await textColumn(page);
      expect(wide.scroll, "html imprint 1440: the page must not scroll sideways").toBeLessThanOrEqual(wide.client);
      expect(wide.right - wide.left, "html imprint 1440: the text column must stay narrower than half the page").toBeLessThan(
        wide.client / 2,
      );
      expect(
        Math.abs(wide.left - (wide.client - wide.right)),
        "html imprint 1440: the text column must sit in the middle of the page",
      ).toBeLessThanOrEqual(1);
    });

    test("design: the imprint carries the title of its role", async ({ page }) => {
      skipUnlessServiceEnabled("design");
      skipWithoutImprint();
      await open(page, imprintUrl());
      expect(imprintTitle(), "IMPRINT_TITLE must be set").toBeTruthy();
      await expect.poll(() => page.title()).toBe(imprintTitle());
      await expect(page.locator(HEADING)).toHaveText(imprintTitle());
    });

    test("design: gallery of the imprint and the 403 page of the proxy", async ({ page }) => {
      skipUnlessServiceEnabled("design");
      test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
      test.setTimeout(resolveTimeout(600_000));
      await captureDesignGallery(page, views());
    });
  });
};
