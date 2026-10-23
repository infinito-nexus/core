const { test, expect } = require("@playwright/test");

const {
  assertDesignTokens,
  assertLightAndDark,
  assertReadable,
  assertToken,
  captureDesignGallery,
  galleryEnabled,
} = require("./design");
const { apiFetchOnion, apiGetOnion, decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const MODES = ["light", "dark"];
const READY_MS = 10_000;
const SHOWCASE = "design-showcase";
const HEADING = ".page-header h1";
const LOGO = `${HEADING} > a > img`;
const LISTING = "#drop-area table.table-hover";
const ROW = `${LISTING} tr`;
const CELL = `${LISTING} tr > td`;
const ENTRY = `${LISTING} tr > td a`;
const OPERATIONS = `${LISTING} tr div.operations`;
const BREADCRUMB = "ol.breadcrumb";
const BUTTON = ".btn-group .btn-default";
const EMPTY = "#drop-area .add-files";
const PROGRESS = "#progress-area .progress-bar";
const RUNNING = `${PROGRESS}:not(.progress-bar-success)`;
const FINISHED = `${PROGRESS}.progress-bar-success`;
const STATUS_ROW = "table.table-striped > tbody > tr";

const TEXT_FILES = ["readme.txt", "notes.md", "data.json"];
const MEDIA_FILES = [
  { name: "chart.svg", mimeType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"/>' },
  { name: "clip.json", mimeType: "application/json", body: '{"design":"showcase"}' },
  { name: "table.csv", mimeType: "text/csv", body: "name,size\nreadme,12\n" },
];
const LONG_NAMES = [
  "a-very-long-object-name-that-has-to-wrap-inside-the-listing-table-on-a-narrow-screen-0001.txt",
  "another-very-long-object-name-with-many-segments-and-a-version-suffix-2026-10-08-final.txt",
];

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

exports.register = function (shared) {
  const { env, keycloakLogin, isAuthChain } = shared;
  const filer = (env.filerUrl || "").replace(/\/$/, "");
  const master = (env.masterUrl || "").replace(/\/$/, "");

  function skipUnlessUiServed() {
    skipUnlessServiceEnabled("design");
    test.skip(!env.frontendEnabled, "frontend disabled (headless backend node)");
    test.skip(!env.ssoEnabled, "SSO disabled: the front proxy answers 403 on both UI domains");
  }

  /**
   * Args:
   *   page: Playwright page.
   *   url: absolute URL on the filer or master domain.
   *   ready: CSS selector that is visible once the view rendered.
   */
  async function open(page, url, ready) {
    await gotoOnion(page, url);
    if (isAuthChain(page.url())) {
      await keycloakLogin(page, env.adminUsername, env.adminPassword);
      await expect.poll(() => isAuthChain(page.url()), { timeout: resolveTimeout(READY_MS) }).toBe(false);
      await gotoOnion(page, url);
    }
    await expect(page.locator(ready).first()).toBeVisible({ timeout: resolveTimeout(READY_MS) });
  }

  /**
   * Args:
   *   page: signed-in Playwright page whose request context carries the proxy session.
   *   directory: filer directory below the showcase root, without slashes at either end.
   *   file: { name, mimeType, body } of the object to store.
   */
  async function upload(page, directory, file) {
    const target = `${filer}/${SHOWCASE}/${directory ? `${directory}/` : ""}`;
    const response = await apiFetchOnion(page.request, target, {
      method: "POST",
      multipart: { file: { name: file.name, mimeType: file.mimeType, buffer: Buffer.from(file.body) } },
    });
    expect(response.ok(), `upload of ${file.name} into ${target}`).toBe(true);
  }

  async function seed(page) {
    const marker = await apiGetOnion(page.request, `${filer}/${SHOWCASE}/empty/`, {
      headers: { Accept: "application/json" },
    });
    if (marker.ok()) return;
    for (const name of TEXT_FILES) {
      await upload(page, "", { name, mimeType: "text/plain", body: `design showcase ${name}\n` });
    }
    await upload(page, "reports/2026", { name: "summary.txt", mimeType: "text/plain", body: "summary\n" });
    for (const file of MEDIA_FILES) await upload(page, "media", file);
    for (const name of LONG_NAMES) await upload(page, "long-names", { name, mimeType: "text/plain", body: "long\n" });
    for (let index = 1; index <= 12; index += 1) {
      const name = `file-${String(index).padStart(2, "0")}.txt`;
      await upload(page, "many", { name, mimeType: "text/plain", body: `${name}\n` });
    }
    const created = await apiFetchOnion(page.request, `${filer}/${SHOWCASE}/empty/`, { method: "POST" });
    expect(created.ok(), "the empty showcase folder is created last and marks a finished seed").toBe(true);
  }

  function shown(ready) {
    return (page) => expect(page.locator(ready).first()).toBeVisible({ timeout: resolveTimeout(READY_MS) });
  }

  async function renderProgress(page) {
    await page.evaluate(() => {
      window.startUpload({ name: "running.bin" });
      window.startUpload({ name: "done.bin" });
      window.reportProgress("running.bin", 60);
      window.reportProgress("done.bin", 100);
    });
    await expect(page.locator(RUNNING).first()).toBeVisible({ timeout: resolveTimeout(READY_MS) });
  }

  function views() {
    const showcase = `${filer}/${SHOWCASE}/`;
    return [
      { name: "master-status", url: `${master}/`, prepare: shown(STATUS_ROW) },
      {
        name: "master-topology-hover",
        url: `${master}/`,
        prepare: async (page) => {
          await shown(STATUS_ROW)(page);
          await page.locator("table.table-striped a").last().hover();
        },
      },
      {
        name: "master-link-focus",
        url: `${master}/`,
        prepare: async (page) => {
          await shown(STATUS_ROW)(page);
          await page.locator("table.table-striped a").first().focus();
        },
      },
      { name: "filer-root", url: `${filer}/`, prepare: shown(ROW) },
      { name: "filer-folder", url: showcase, prepare: shown(ROW) },
      {
        name: "filer-row-hover",
        url: showcase,
        prepare: async (page) => {
          await shown(ROW)(page);
          await page.locator(ROW).first().hover();
          await shown(OPERATIONS)(page);
        },
      },
      {
        name: "filer-row-action-hover",
        url: showcase,
        prepare: async (page) => {
          await shown(ROW)(page);
          await page.locator(ROW).first().hover();
          await page.locator(`${OPERATIONS} .btn`).first().hover();
        },
      },
      { name: "filer-nested-folder", url: `${showcase}reports/2026/`, prepare: shown(ROW) },
      { name: "filer-empty-folder", url: `${showcase}empty/`, prepare: shown(EMPTY) },
      { name: "filer-media-folder", url: `${showcase}media/`, prepare: shown(ROW) },
      { name: "filer-long-names", url: `${showcase}long-names/`, prepare: shown(ROW) },
      { name: "filer-load-more", url: `${showcase}many/?limit=5`, prepare: shown("a:has-text('Load more')") },
      { name: "filer-second-page", url: `${showcase}many/?limit=5&lastFileName=file-05.txt`, prepare: shown(ROW) },
      { name: "filer-name-pattern", url: `${showcase}?namePattern=*.txt`, prepare: shown(ROW) },
      { name: "filer-buckets", url: `${filer}/buckets/`, prepare: shown(HEADING) },
      {
        name: "filer-button-hover",
        url: showcase,
        prepare: async (page) => {
          await shown(ROW)(page);
          await page.locator(BUTTON).first().hover();
        },
      },
      {
        name: "filer-breadcrumb-focus",
        url: `${showcase}reports/2026/`,
        prepare: async (page) => {
          await shown(ROW)(page);
          await page.locator(`${BREADCRUMB} a`).nth(1).focus();
        },
      },
      {
        name: "filer-entry-focus",
        url: showcase,
        prepare: async (page) => {
          await shown(ROW)(page);
          await page.locator(ENTRY).first().focus();
        },
      },
      {
        name: "filer-upload-progress",
        url: showcase,
        prepare: async (page) => {
          await shown(ROW)(page);
          await renderProgress(page);
        },
      },
      {
        name: "filer-drop-highlight",
        url: showcase,
        prepare: async (page) => {
          await shown(ROW)(page);
          await page.locator("#drop-area").dispatchEvent("dragenter");
          await expect(page.locator("#drop-area")).toHaveClass(/highlight/);
        },
      },
    ];
  }

  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessUiServed();
    await open(page, `${filer}/`, HEADING);
    await assertDesignTokens(page, "seaweedfs filer");
    await open(page, `${master}/`, HEADING);
    await assertDesignTokens(page, "seaweedfs master");
  });

  test("design: the filer listing, its buttons, its dividers and its focus ring take the palette", async ({ page }) => {
    skipUnlessUiServed();
    await open(page, `${filer}/`, HEADING);
    await seed(page);
    await open(page, `${filer}/${SHOWCASE}/`, ROW);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await page.mouse.move(0, 0);
      await assertToken(page, "body", "background-color", "--design-surface-1", `page ${mode}`);
      await assertToken(page, "body", "color", "--design-text", `text ${mode}`);
      await assertToken(page, ENTRY, "color", "--design-link", `entry link ${mode}`);
      await assertToken(page, CELL, "border-top-color", "--design-border", `row divider ${mode}`);
      await assertToken(page, ".page-header", "border-bottom-color", "--design-border", `header divider ${mode}`);
      await assertToken(page, BREADCRUMB, "background-color", "--design-surface-3", `breadcrumb ${mode}`);
      await assertToken(page, BUTTON, "background-color", "--design-surface-2", `button ${mode}`);
      await assertToken(page, BUTTON, "color", "--design-text", `button ${mode}`);
      await assertToken(page, BUTTON, "border-top-color", "--design-border-strong", `button ${mode}`);
      await page.locator(BUTTON).first().hover();
      await assertToken(page, BUTTON, "background-color", "--design-surface-hover", `hovered button ${mode}`);
      await page.locator(ROW).first().hover();
      await assertToken(page, ROW, "background-color", "--design-surface-hover", `hovered row ${mode}`);
      await expect(page.locator(OPERATIONS).first()).toBeVisible();
      await page.locator(ENTRY).first().focus();
      await assertToken(page, `${ENTRY}:focus`, "outline-color", "--design-link", `focused entry ${mode}`);
      await expect(page.locator(`${ENTRY}:focus`)).toHaveCSS("outline-style", "solid");
    }
    await page.mouse.move(0, 0);
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, "body", "seaweedfs filer page");
    await assertLightAndDark(page, BREADCRUMB, "seaweedfs breadcrumb");
    await assertReadable(page, [HEADING, `${HEADING} small`, ENTRY, CELL, BUTTON, `${BREADCRUMB} a`], "seaweedfs filer");
  });

  test("design: the master status tables take the palette", async ({ page }) => {
    skipUnlessUiServed();
    await open(page, `${master}/`, STATUS_ROW);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "body", "background-color", "--design-surface-1", `page ${mode}`);
      await assertToken(page, `${STATUS_ROW}:nth-child(odd)`, "background-color", "--design-surface-2", `striped row ${mode}`);
      await assertToken(page, `${STATUS_ROW} > th`, "border-top-color", "--design-border", `row divider ${mode}`);
      await assertToken(page, `${STATUS_ROW} > th`, "color", "--design-text", `row label ${mode}`);
      await assertToken(page, "td > code", "background-color", "--design-surface-3", `data center ${mode}`);
      await assertToken(page, `${HEADING} small`, "color", "--design-text-muted", `version ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, `${STATUS_ROW}:nth-child(odd) > th`, "seaweedfs striped row");
    await assertReadable(page, [HEADING, `${STATUS_ROW} > th`, `${STATUS_ROW} > td`, "td > code", "table.table-striped a"], "seaweedfs master");
  });

  test("design: the upload progress bar is the primary fill and carries its on-color", async ({ page }) => {
    skipUnlessUiServed();
    await open(page, `${filer}/`, HEADING);
    await seed(page);
    await open(page, `${filer}/${SHOWCASE}/`, ROW);
    expect(
      await page.evaluate(() => typeof window.reportProgress),
      "the inline script of the filer page ran (script-src-elem allows it)",
    ).toBe("function");
    await renderProgress(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, RUNNING, "background-color", "--design-primary", `running ${mode}`);
      await assertToken(page, RUNNING, "color", "--design-on-primary", `running ${mode}`);
      await assertToken(page, FINISHED, "background-color", "--design-success", `finished ${mode}`);
      await assertToken(page, FINISHED, "color", "--design-on-success", `finished ${mode}`);
      await expect(page.locator(RUNNING).first()).toHaveCSS("background-image", "none");
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: the pages follow the browser preference and set no theme attribute", async ({ page }) => {
    skipUnlessUiServed();
    await open(page, `${filer}/`, HEADING);
    expect(await page.locator("html").getAttribute("data-design-theme"), "the app has no theme switch").toBeNull();
    await assertLightAndDark(page, "body", "seaweedfs follows prefers-color-scheme");
  });

  test("design: both pages show the generated logo, the configured title and the favicon", async ({ page }) => {
    skipUnlessUiServed();
    const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL);
    const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL);
    const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE);
    test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");

    for (const [url, suffix] of [
      [`${filer}/`, " Filer"],
      [`${master}/`, ""],
    ]) {
      await open(page, url, HEADING);
      if (title) {
        await expect(page).toHaveTitle(new RegExp(`^${escapeRegExp(`${title}${suffix}`)}\\s`));
        await expect(page.locator(HEADING)).toContainText(`${title}${suffix}`);
      }
      if (logoUrl) {
        await expect(page.locator(LOGO)).toHaveCSS("content", `url("${logoUrl}")`);
        const box = await page.locator(LOGO).boundingBox();
        expect(Math.round(box.width), "the logo keeps the 50 px box of upstream").toBe(50);
        expect(Math.round(box.height), "the logo keeps the 50 px box of upstream").toBe(50);
        await expect(page.locator("link[rel~='icon']")).toHaveAttribute("href", faviconUrl);
      }
    }
    for (const assetUrl of [logoUrl, faviconUrl].filter(Boolean)) {
      expect((await apiGetOnion(page.request, assetUrl)).ok(), `${assetUrl} is published on the CDN`).toBe(true);
    }
  });

  test("design: gallery of master status and filer listings", async ({ page }) => {
    skipUnlessUiServed();
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(2_400_000));

    await open(page, `${filer}/`, HEADING);
    await seed(page);
    await captureDesignGallery(page, views());
  });
};
