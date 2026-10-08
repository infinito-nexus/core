const fs = require("node:fs");

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

const STORAGE_KEYS = ["dark-mode-preference", "qrCodeConfig", "qr-scanner-camera-preference"];
const INJECTED_SNIPPETS = /<!--infinito-inj-->[\s\S]*?<!--\/infinito-inj-->/g;
const READY = "#settings #data";
const PAGE = "#app > main > .min-h-screen";
const PREVIEW = "#element-to-export";
const QR = "[role='img'][aria-label^='QR code'] svg";
const TOGGLE = "button[aria-label='Toggle dark mode']:visible";
const MENU = "button[aria-label='Menu']";
const MODAL = "[role='dialog'][aria-labelledby='data-to-encode-modal-title']";
const SAVE = `${MODAL} .border-t > .button`;
const SELECTED_MODE = "button[aria-label='Switch to Create Mode']:visible";
const HEADER_ICON = "#app a.icon-button:visible";
const RADIO = "#settings input[type='radio']";
const EXPORT_PNG = "#download-qr-image-button-png";
const POPOVER = "[cmdk-input-wrapper] input";
const CSV_INPUT = "input[type='file'][accept='.csv,.txt']";
const IMAGE_INPUT = "input[type='file'][accept='image/*']";
const ROLE_SHEET = "link[rel='stylesheet'][href*='web-app-mini-qr'][href*='style.css']";
const SAMPLE = "https://example.org/design";
const BLANK_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);
const BATCH_CSV = ["url,frameText,fileName", "https://example.org/a,Scan A,code-a", "https://example.org/b,Scan B,code-b"].join(
  "\n",
);

function baseUrl() {
  return decodeDotenvQuotedValue(process.env.APP_BASE_URL || "").replace(/\/$/, "");
}

function designTitle() {
  return decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
}

function designFaviconUrl() {
  return decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");
}

function designLogoUrl() {
  return decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
}

async function fresh(page) {
  await page.addInitScript((keys) => {
    try {
      for (const key of keys) window.localStorage.removeItem(key);
      window.localStorage.setItem("preferred-language", "en");
    } catch (error) {
      void error;
    }
  }, STORAGE_KEYS);
}

async function open(page) {
  await gotoOnion(page, `${baseUrl()}/`);
  await page.locator(READY).first().waitFor({ state: "visible", timeout: resolveTimeout(20_000) });
}

async function stripInjectedSnippets(route) {
  if (route.request().resourceType() !== "document") return route.continue();
  const response = await route.fetch();
  return route.fulfill({ response, body: (await response.text()).replace(INJECTED_SNIPPETS, "") });
}

async function quiet(page) {
  await page.waitForFunction(
    () =>
      document
        .getAnimations()
        .every((a) => a.playState !== "running" || a.effect?.getComputedTiming().iterations === Infinity),
    null,
    { timeout: resolveTimeout(10_000) },
  );
}

function narrow(page) {
  return page.viewportSize().width < 768;
}

async function darkClass(page) {
  return page.evaluate(() => document.documentElement.classList.contains("dark"));
}

async function openTools(page) {
  if (!narrow(page)) return;
  await page.locator(MENU).click({ timeout: resolveTimeout(10_000) });
  await page.locator(TOGGLE).waitFor({ state: "visible", timeout: resolveTimeout(10_000) });
  await quiet(page);
}

async function pickScheme(page, clicks) {
  await openTools(page);
  for (let count = 0; count < clicks; count += 1) {
    await page.locator(TOGGLE).click({ timeout: resolveTimeout(10_000) });
  }
}

async function setData(page, text) {
  const code = page.locator(QR).first();
  const before = narrow(page) ? null : await code.innerHTML();
  await page.locator("#data").fill(text);
  if (before === null) return;
  await expect.poll(() => code.innerHTML(), { timeout: resolveTimeout(10_000) }).not.toBe(before);
}

async function openExport(page) {
  if (narrow(page)) {
    await page.locator("#drawer-preview-container").click({ timeout: resolveTimeout(10_000) });
  }
  await page.locator(`${EXPORT_PNG}:enabled`).waitFor({ state: "visible", timeout: resolveTimeout(10_000) });
  await quiet(page);
}

async function enableFrame(page) {
  await page.locator("#frame-settings-title").click({ timeout: resolveTimeout(10_000) });
  await page.locator("#show-frame").check({ timeout: resolveTimeout(10_000) });
  await page.locator("#frame-text").waitFor({ state: "visible", timeout: resolveTimeout(10_000) });
  await quiet(page);
}

async function openCombobox(page, label) {
  await page.locator(`button[role='combobox'][aria-label='${label}']:visible`).click({ timeout: resolveTimeout(10_000) });
  await page.locator(POPOVER).waitFor({ state: "visible", timeout: resolveTimeout(10_000) });
  await quiet(page);
}

async function openModal(page, type) {
  await page.locator("button[aria-label='Open data type generator']").click({ timeout: resolveTimeout(10_000) });
  await page.locator(MODAL).waitFor({ state: "visible", timeout: resolveTimeout(10_000) });
  await page.locator("#dataType").selectOption(type);
  await quiet(page);
}

async function failModal(page) {
  await openModal(page, "url");
  await page.locator(SAVE).click({ timeout: resolveTimeout(10_000) });
  await page.locator(`${MODAL} p.text-red-500`).first().waitFor({ state: "visible", timeout: resolveTimeout(10_000) });
  await page.mouse.move(0, 0);
}

async function toBatch(page) {
  await page.getByRole("button", { name: "Batch export", exact: true }).click({ timeout: resolveTimeout(10_000) });
  await page.locator(CSV_INPUT).waitFor({ state: "attached", timeout: resolveTimeout(10_000) });
}

async function openGuide(page) {
  await toBatch(page);
  await page.getByRole("button", { name: "CSV Format Guide" }).click({ timeout: resolveTimeout(10_000) });
  await page.getByRole("button", { name: "vCard Contact" }).waitFor({ state: "visible", timeout: resolveTimeout(10_000) });
  await quiet(page);
}

async function toScan(page) {
  await page.locator("button[aria-label='Switch to Scan Mode']:visible").click({ timeout: resolveTimeout(10_000) });
  await page.locator(".capture-controls").waitFor({ state: "visible", timeout: resolveTimeout(10_000) });
}

async function openChangelog(page) {
  await openTools(page);
  await page.locator("button[aria-label='View changelog']:visible").click({ timeout: resolveTimeout(10_000) });
  await page.locator("[role='dialog'] .prose h2").first().waitFor({ state: "visible", timeout: resolveTimeout(20_000) });
  await quiet(page);
}

async function qrPaint(page) {
  return page.evaluate((preview) => {
    const ctx = document.createElement("canvas").getContext("2d");
    const rgb = (value) => {
      ctx.fillStyle = "#000";
      ctx.fillStyle = value;
      return ctx.fillStyle;
    };
    return {
      background: rgb(getComputedStyle(document.querySelector(preview)).backgroundColor),
      expectedBackground: rgb(document.querySelector("#background-color").value),
      fills: Array.from(document.querySelectorAll(`${preview} svg [fill]`), (node) => [
        rgb(node.getAttribute("fill")),
        rgb(getComputedStyle(node).fill),
      ]).filter(([attribute]) => /^#/.test(attribute)),
    };
  }, PREVIEW);
}

async function roleSheet(page, request) {
  const href = await page.locator(ROLE_SHEET).first().getAttribute("href");
  const response = await apiGetOnion(request, href, { timeout: resolveTimeout(30_000) });
  expect(response.status(), "mini-qr: the role stylesheet must be served").toBe(200);
  return response.text();
}

async function rulesInsidePreview(page, css) {
  const selectors = css
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("}")
    .map((rule) => rule.split("{")[0].trim())
    .filter(Boolean);
  expect(selectors.length, "mini-qr: the role stylesheet must carry rules").toBeGreaterThan(20);
  return page.evaluate(
    ([list, preview]) => {
      const nodes = Array.from(document.querySelectorAll(`${preview}, ${preview} *`));
      return list.filter((selector) => {
        try {
          return nodes.some((node) => node.matches(selector.replace(/::[\w-]+/g, "")));
        } catch (error) {
          void error;
          return true;
        }
      });
    },
    [selectors, PREVIEW],
  );
}

async function exportPng(page) {
  await setData(page, SAMPLE);
  const [download] = await Promise.all([
    page.waitForEvent("download", { timeout: resolveTimeout(30_000) }),
    page.locator(EXPORT_PNG).click({ timeout: resolveTimeout(10_000) }),
  ]);
  return fs.readFileSync(await download.path());
}

function view(name, prepare) {
  return {
    name,
    url: `${baseUrl()}/`,
    prepare: async (page) => {
      await page.locator(READY).first().waitFor({ state: "visible", timeout: resolveTimeout(20_000) });
      if (prepare) await prepare(page);
    },
  };
}

function views() {
  const hover = (selector) => (page) => page.locator(selector).first().hover({ timeout: resolveTimeout(10_000) });
  return [
    view("create"),
    view("create-with-data", (page) => setData(page, SAMPLE)),
    view("data-focus", (page) => page.locator("#data").focus()),
    view("export-panel", async (page) => {
      await setData(page, SAMPLE);
      await openExport(page);
    }),
    view("export-button-hover", async (page) => {
      await setData(page, SAMPLE);
      await openExport(page);
      await hover(EXPORT_PNG)(page);
    }),
    view("frame-enabled", async (page) => {
      await setData(page, SAMPLE);
      await enableFrame(page);
    }),
    view("frame-preset-open", async (page) => {
      await setData(page, SAMPLE);
      await enableFrame(page);
      await openCombobox(page, "Select frame preset");
    }),
    view("preset-open", (page) => openCombobox(page, "Select QR code preset")),
    view("settings-colors", (page) => page.locator("#with-background").uncheck({ timeout: resolveTimeout(10_000) })),
    view("settings-types", (page) =>
      page.locator("#dots-squares-settings fieldset").last().scrollIntoViewIfNeeded({ timeout: resolveTimeout(10_000) }),
    ),
    view("data-templates-wifi", (page) => openModal(page, "wifi")),
    view("data-templates-vcard", (page) => openModal(page, "vcard")),
    view("data-templates-error", failModal),
    view("batch-guide", openGuide),
    view("batch-preview", async (page) => {
      await toBatch(page);
      await page.locator(CSV_INPUT).setInputFiles({ name: "batch.csv", mimeType: "text/csv", buffer: Buffer.from(BATCH_CSV) });
      await page.locator("#settings code").first().waitFor({ state: "visible", timeout: resolveTimeout(10_000) });
    }),
    view("scan", toScan),
    view("scan-error", async (page) => {
      await toScan(page);
      await page.locator(IMAGE_INPUT).setInputFiles({ name: "blank.png", mimeType: "image/png", buffer: BLANK_PNG });
      await page.locator(".capture-controls p.text-red-500").waitFor({ state: "visible", timeout: resolveTimeout(20_000) });
    }),
    view("header-tools", async (page) => {
      await openTools(page);
      await hover(TOGGLE)(page);
    }),
    view("language-open", async (page) => {
      await openTools(page);
      await openCombobox(page, "Select language");
    }),
    view("theme-forced-dark", (page) => pickScheme(page, 2)),
    view("changelog", openChangelog),
  ];
}

exports.register = function () {
  test.describe("design", () => {
    test.use({ serviceWorkers: "block" });

    test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
      skipUnlessServiceEnabled("design");
      await fresh(page);
      await open(page);
      await assertDesignTokens(page, "mini-qr");
    });

    test("design: page, fields, controls, primary action and divider take the tokens in both modes", async ({ page }) => {
      skipUnlessServiceEnabled("design");
      await fresh(page);
      await open(page);
      await failModal(page);
      for (const mode of ["light", "dark"]) {
        const label = `mini-qr ${mode}`;
        await page.emulateMedia({ colorScheme: mode });
        await expect.poll(() => darkClass(page)).toBe(mode === "dark");
        await assertToken(page, "body", "background-color", "--design-surface-1", label);
        await assertToken(page, PAGE, "background-color", "--design-surface-1", label);
        await assertToken(page, "label[for='data']", "color", "--design-text", label);
        await assertToken(page, "#data", "background-color", "--design-surface-2", label);
        await assertToken(page, "#data", "color", "--design-text", label);
        await assertToken(page, "#copy-qr-image-button", "background-color", "--design-surface-3", label);
        await assertToken(page, "#settings .secondary-button", "background-color", "--design-surface-2", label);
        await assertToken(page, SELECTED_MODE, "background-color", "--design-surface-2", label);
        await assertToken(page, SAVE, "background-color", "--design-surface-3", label);
        await assertToken(page, SAVE, "color", "--design-text", label);
        await assertToken(page, `${MODAL} p.text-red-500`, "color", "--design-danger", label);
        await assertToken(page, `${MODAL} .border-t`, "border-top-color", "--design-border", label);
        await assertToken(page, EXPORT_PNG, "background-color", "--design-primary", label);
        await assertToken(page, EXPORT_PNG, "color", "--design-on-primary", label);
        await assertToken(page, HEADER_ICON, "color", "--design-text", label);
        const primary = await tokenValue(page, "--design-primary", "color");
        await expect
          .poll(() => page.locator(RADIO).first().evaluate((radio) => getComputedStyle(radio, "::before").color), {
            message: `${label}: the radio mark must take --design-primary`,
          })
          .toBe(primary);
        await expect
          .poll(() => page.locator(HEADER_ICON).first().evaluate((icon) => getComputedStyle(icon).backgroundColor), {
            message: `${label}: a header icon button must not carry a fill`,
          })
          .toBe("rgba(0, 0, 0, 0)");
        await expect
          .poll(
            () =>
              page.locator(`${HEADER_ICON} svg path`).first().evaluate((path) => {
                const style = getComputedStyle(path);
                return style.fill === getComputedStyle(path.closest("a, button")).color;
              }),
            { message: `${label}: a header icon must take the color of its control` },
          )
          .toBe(true);
      }
      await page.emulateMedia({ colorScheme: null });
    });

    test("design: the generator stays readable in light and dark mode", async ({ page }) => {
      skipUnlessServiceEnabled("design");
      await fresh(page);
      await open(page);
      await assertLightAndDark(page, "#settings", "mini-qr generator");
      await assertReadable(
        page,
        [
          "label[for='data']",
          "#data",
          "#copy-qr-image-button",
          EXPORT_PNG,
          "#frame-settings-title",
          "#settings .secondary-button",
          "#settings .radio label",
          "#settings legend",
          "button[aria-label='Switch to Create Mode']",
          "button[aria-label='Switch to Scan Mode']",
          "#export-options p",
          { selector: "footer a", optional: true },
        ],
        "mini-qr generator",
      );
      await failModal(page);
      await assertReadable(page, [`${MODAL} h2`, `${MODAL} label`, `${MODAL} input`, SAVE, `${MODAL} p.text-red-500`], "mini-qr dialog");
    });

    test("design: the theme switch drives the tokens", async ({ page }) => {
      skipUnlessServiceEnabled("design");
      await fresh(page);
      await page.emulateMedia({ colorScheme: "light" });
      await open(page);
      const light = await tokenValue(page, "--design-surface-1", "color");
      await expect(page.locator("html")).not.toHaveAttribute("data-design-theme", /.+/);
      await pickScheme(page, 2);
      await expect(page.locator("html")).toHaveClass(/(^|\s)dark(\s|$)/);
      await expect(page.locator("html")).toHaveAttribute("data-design-theme", "dark");
      await expect.poll(() => tokenValue(page, "--design-surface-1", "color")).not.toBe(light);
      await assertToken(page, PAGE, "background-color", "--design-surface-1", "mini-qr forced dark");
      await assertToken(page, "#data", "color", "--design-text", "mini-qr forced dark");
      await page.locator(TOGGLE).click({ timeout: resolveTimeout(10_000) });
      await expect(page.locator("html")).not.toHaveAttribute("data-design-theme", /.+/);
      await page.emulateMedia({ colorScheme: "dark" });
      await expect.poll(() => darkClass(page)).toBe(true);
      await page.locator(TOGGLE).click({ timeout: resolveTimeout(10_000) });
      await expect(page.locator("html")).toHaveAttribute("data-design-theme", "light");
      await expect.poll(() => darkClass(page)).toBe(false);
      await expect.poll(() => tokenValue(page, "--design-surface-1", "color")).toBe(light);
      await assertToken(page, PAGE, "background-color", "--design-surface-1", "mini-qr forced light");
      await page.emulateMedia({ colorScheme: null });
    });

    test("design: the QR code keeps the colors the user chose", async ({ page, request }) => {
      skipUnlessServiceEnabled("design");
      await fresh(page);
      await open(page);
      await page.locator(`${PREVIEW} svg`).waitFor({ state: "visible", timeout: resolveTimeout(20_000) });
      for (const mode of ["light", "dark"]) {
        await page.emulateMedia({ colorScheme: mode });
        await expect.poll(() => darkClass(page)).toBe(mode === "dark");
        const paint = await qrPaint(page);
        expect(paint.background, `mini-qr ${mode}: the preview background is the chosen one`).toBe(paint.expectedBackground);
        expect(paint.fills.length, `mini-qr ${mode}: the preview must carry fill colors`).toBeGreaterThan(0);
        for (const [attribute, computed] of paint.fills) {
          expect(computed, `mini-qr ${mode}: a QR fill must stay ${attribute}`).toBe(attribute);
        }
      }
      await page.emulateMedia({ colorScheme: null });
      await enableFrame(page);
      await expect(page.locator(`${PREVIEW} p`).first()).toBeVisible();
      expect(
        await rulesInsidePreview(page, await roleSheet(page, request)),
        "mini-qr: no rule of the role stylesheet may match inside the preview",
      ).toEqual([]);
    });

    test("design: an exported image is the same with and without the design", async ({ page }) => {
      skipUnlessServiceEnabled("design");
      await fresh(page);
      await open(page);
      await expect(page.locator(ROLE_SHEET)).toHaveCount(1);
      const designed = await exportPng(page);
      await page.route("**/*", stripInjectedSnippets);
      await open(page);
      await expect(page.locator(ROLE_SHEET)).toHaveCount(0);
      const plain = await exportPng(page);
      await page.unroute("**/*", stripInjectedSnippets);
      expect(designed.length, "mini-qr: the export must carry an image").toBeGreaterThan(1000);
      expect(designed.equals(plain), "mini-qr: the exported PNG must not depend on the design").toBe(true);
    });

    test("design: logo, favicon and title are the configured ones", async ({ page }) => {
      skipUnlessServiceEnabled("design");
      test.skip(!designLogoUrl() || !designTitle(), "logo or title replacement is switched off");
      await fresh(page);
      await open(page);
      await expect.poll(() => page.title()).toBe(designTitle());
      await expect
        .poll(() => page.evaluate(() => document.querySelector("link[rel='icon']").href))
        .toBe(designFaviconUrl());
      for (const size of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
        await page.setViewportSize(size);
        await openTools(page);
        const brand = page.locator("#app h1:visible").first();
        await expect(brand).toBeVisible();
        expect(await brand.evaluate((heading) => getComputedStyle(heading).backgroundImage)).toContain(designLogoUrl());
        const box = await brand.boundingBox();
        expect(box.width, `mini-qr ${size.width}: the brand box must be wider than high`).toBeGreaterThan(box.height * 1.5);
      }
      const lockup = await page.evaluate(
        (source) =>
          new Promise((resolve) => {
            const image = new Image();
            image.onload = () => resolve(image.naturalWidth);
            image.onerror = () => resolve(0);
            image.src = source;
          }),
        designLogoUrl(),
      );
      expect(lockup, "mini-qr: the lockup must load").toBeGreaterThan(0);
    });

    test("design: gallery of the generator and the scanner", async ({ page }) => {
      skipUnlessServiceEnabled("design");
      test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
      test.setTimeout(resolveTimeout(1_800_000));
      await fresh(page);
      await captureDesignGallery(page, views());
    });

  });
};
