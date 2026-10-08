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

const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
const faviconIcoUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");
const faviconPngUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_PNG_URL || "");
const faviconSvgUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_SVG_URL || "");

const MODES = ["light", "dark"];
const SOURCE = "social.example";
const QUIET_SOURCE = "quiet.example";
const BROKEN_SOURCE = "down.example";
const HTML = "html";
const INFO_BAR = "#page header";
const CARD = ".wall-item .card";
const CARD_HEADER = ".wall-item .card-header";
const CARD_TEXT = ".wall-item .card-body > .card-text";
const DISPLAY_NAME = ".wall-item .displayname";
const PROFILE = ".wall-item .profile";
const PINNED_HEADER = ".wall-item .card.pinned .card-header";
const CARD_MENU_BUTTON = ".wall-item .dropdown > button";
const CARD_MENU = ".wall-item .dropdown-menu.show";
const FOOTER = "#page footer";
const STATUS = "#page footer aside";
const STATUS_ICONS = "#status-row";
const ERROR_ICON = "#status-row [data-icon='triangle-exclamation']";
const CUSTOMIZE = "#page footer button[data-bs-target='#configModal']";
const THEME_TOGGLE = "#page footer button:not([data-bs-target])";
const DIALOG = "#configModal.show .modal-content";
const APPLY = "#configModal .btn-primary";
const SOURCES_FIELD = "#ctab-content #edit-server";
const TITLE_FIELD = "#edit-title";
const CHECKBOX = "#edit-nsfw";
const WALL_LINK = "body > ul > li > a";

/**
 * Args:
 *   sources: `{ quiet, broken }`, the server names whose timelines answer empty and with an error; every other server answers with the showcase posts.
 */
function installFediverseFixture(sources) {
  const minutesAgo = (count) => new Date(Date.now() - count * 60_000).toISOString();
  const picture = (label, width, height) => {
    const svg =
      `<svg xmlns='http://www.w3.org/2000/svg' width='${width}' height='${height}'>` +
      "<defs><pattern id='p' width='12' height='12' patternUnits='userSpaceOnUse' patternTransform='rotate(45)'>" +
      "<rect width='6' height='12' fill='silver' opacity='0.35'/></pattern></defs>" +
      "<rect width='100%' height='100%' fill='gray'/><rect width='100%' height='100%' fill='url(#p)'/>" +
      `<text x='50%' y='55%' text-anchor='middle' font-family='sans-serif' font-size='${Math.round(height / 4)}' fill='white'>${label}</text></svg>`;
    return `data:image/svg+xml,${encodeURIComponent(svg)}`;
  };
  const account = (name) => ({
    id: name,
    username: name,
    acct: name,
    display_name: name.charAt(0).toUpperCase() + name.slice(1),
    avatar: picture(name.charAt(0).toUpperCase(), 96, 96),
    avatar_static: picture(name.charAt(0).toUpperCase(), 96, 96),
    bot: false,
    locked: false,
    emojis: [],
    created_at: minutesAgo(500_000),
    url: `https://social.example/@${name}`,
  });
  const status = (index, author, content, media) => ({
    id: String(index),
    uri: `https://social.example/statuses/${index}`,
    url: `https://social.example/@${author}/${index}`,
    account: account(author),
    created_at: minutesAgo(index * 9 + 2),
    content,
    emojis: [],
    tags: [],
    media_attachments: media
      ? [{ id: `m${index}`, type: "image", url: picture(media, 640, 400), preview_url: picture(media, 640, 400), description: media }]
      : [],
    sensitive: false,
    visibility: "public",
    in_reply_to_id: null,
    language: "en",
    reblog: null,
  });
  const link = "<a href='https://social.example/tags/fediverse' class='mention hashtag'>#<span>fediverse</span></a>";
  const posts = [
    status(1, "biber", `<p>A wall of public posts from the ${link}, refreshed while you watch.</p>`, "Wall"),
    status(2, "ada", "<p>Short note without media.</p>"),
    status(3, "grace", `<p>Hosting your own services keeps your data where you can reach it. ${link}</p>`, "Server"),
    status(4, "linus", "<p>Second paragraph test.</p><p>Posts keep their paragraphs, links and line breaks on the wall.</p>"),
    status(5, "biber", `<p>Photos fill the width of a card. ${link}</p>`, "Photo"),
    status(6, "ada", "<p>A longer post shows how a card grows with its text: the grid packs cards of different heights next to each other and moves them when a new post arrives at the top.</p>"),
    status(7, "grace", `<p>Open standards connect communities. ${link}</p>`),
    status(8, "linus", "<p>Media only walls hide the text of a post.</p>", "Gallery"),
  ];
  const answer = (body, code) =>
    Promise.resolve(new Response(JSON.stringify(body), { status: code, headers: { "content-type": "application/json" } }));
  const real = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const url = new URL(typeof input === "string" ? input : input.url, window.location.href);
    if (!url.pathname.startsWith("/api/v1/")) return real(input, init);
    if (url.hostname === sources.broken) return answer({ error: "Service unavailable" }, 503);
    if (url.hostname === sources.quiet) return answer([], 200);
    if (url.pathname.endsWith("/accounts/lookup")) return answer(account(url.searchParams.get("acct")), 200);
    return answer(posts, 200);
  };
}

/**
 * Args:
 *   page: Playwright page that shows a wall; the pointer moves into the page margin, off the info bar and off every card.
 */
async function parkPointer(page) {
  await page.mouse.move(2, 200);
}

/**
 * Args:
 *   page: Playwright page that shows a wall with cards; resolves once every image is loaded and the masonry grid has stopped moving.
 */
async function wallSettled(page) {
  await expect(page.locator(CARD).first()).toBeVisible({ timeout: resolveTimeout(60_000) });
  await parkPointer(page);
  let previous = "";
  await expect
    .poll(
      async () => {
        const current = await page.evaluate(() => {
          const moving = document
            .getAnimations()
            .some((animation) => animation.playState === "running" && animation.effect?.target?.closest(".wall-item"));
          if (moving || Array.from(document.images).some((image) => !image.complete)) return "";
          return Array.from(document.querySelectorAll(".wall-item"), (item) => {
            const box = item.getBoundingClientRect();
            return [box.left, box.top, box.height].map(Math.round).join(":");
          }).join("|");
        });
        const stable = current !== "" && current === previous;
        previous = current;
        return stable;
      },
      { message: "the masonry grid must stop moving", intervals: [800, 150], timeout: resolveTimeout(30_000) },
    )
    .toBe(true);
}

async function scrolledToTop(page) {
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
}

async function statusShown(page, text) {
  await expect(page.locator(STATUS)).toContainText(text, { timeout: resolveTimeout(60_000) });
  await parkPointer(page);
}

async function openDialog(page, tab) {
  await expect(page.locator(CUSTOMIZE)).toBeVisible({ timeout: resolveTimeout(60_000) });
  await page.locator(CUSTOMIZE).click();
  await expect(page.locator(DIALOG)).toBeVisible({ timeout: resolveTimeout(30_000) });
  await expect(page.locator(DIALOG)).toHaveCSS("opacity", "1");
  await parkPointer(page);
  if (tab) {
    await page.locator(`#btab-${tab}`).click();
    await expect(page.locator(`#ctab-${tab}`)).toBeVisible({ timeout: resolveTimeout(30_000) });
  }
}

async function openCardMenu(page) {
  await wallSettled(page);
  await page.locator(CARD).first().hover();
  await page.locator(CARD_MENU_BUTTON).first().click();
  await expect(page.locator(CARD_MENU)).toBeVisible({ timeout: resolveTimeout(30_000) });
}

exports.register = function (shared) {
  const wall = `${shared.env.appBaseUrl}/${shared.env.defaultSlug}/`;
  const seeded = (query = "") => `${wall}?servers=${SOURCE}&interval=600${query}`;

  async function openWall(page, url = seeded()) {
    await page.addInitScript(installFediverseFixture, { quiet: QUIET_SOURCE, broken: BROKEN_SOURCE });
    await gotoOnion(page, url);
    await wallSettled(page);
  }

  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openWall(page);
    await assertDesignTokens(page, "fediwall");
  });

  test("design: the wall takes surfaces, text, dividers and links from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openWall(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await expect(page.locator(HTML)).toHaveAttribute("data-bs-theme", mode);
      await assertToken(page, "body", "background-color", "--design-surface-1", `wall ${mode}`);
      await assertToken(page, INFO_BAR, "background-color", "--design-surface-2", `info bar ${mode}`);
      await assertToken(page, INFO_BAR, "border-bottom-color", "--design-border", `info bar divider ${mode}`);
      await assertToken(page, CARD, "background-color", "--design-surface-2", `card ${mode}`);
      await assertToken(page, CARD, "box-shadow", "--design-shadow-2", `card ${mode}`);
      await assertToken(page, CARD_HEADER, "background-color", "--design-surface-3", `card header ${mode}`);
      await assertToken(page, CARD_HEADER, "border-bottom-color", "--design-border", `card divider ${mode}`);
      await assertToken(page, CARD_TEXT, "color", "--design-text", `card text ${mode}`);
      await assertToken(page, PROFILE, "color", "--design-text-muted", `profile ${mode}`);
      await expect(page.locator(PROFILE).first(), `profile ${mode}`).toHaveCSS("opacity", "1");
      await assertToken(page, `${CARD_TEXT} a`, "color", "--design-link", `post link ${mode}`);
      await assertToken(page, `${FOOTER} a:not(.text-muted)`, "color", "--design-link", `footer link ${mode}`);
      await assertToken(page, STATUS, "color", "--design-text-muted", `status line ${mode}`);
      await expect(page.locator(STATUS), `status line ${mode}`).toHaveCSS("opacity", "1");
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, CARD, "fediwall wall");
    await assertReadable(
      page,
      [INFO_BAR, DISPLAY_NAME, PROFILE, CARD_TEXT, `${CARD_TEXT} a`, STATUS, THEME_TOGGLE, `${FOOTER} a`],
      "fediwall wall",
    );
    await page.locator(THEME_TOGGLE).hover();
    await assertToken(page, THEME_TOGGLE, "background-color", "--design-surface-hover", "hovered footer button");
    await assertReadable(page, [THEME_TOGGLE], "fediwall hovered footer button");
  });

  test("design: a failing source is marked in a status color", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.addInitScript(installFediverseFixture, { quiet: QUIET_SOURCE, broken: BROKEN_SOURCE });
    await gotoOnion(page, `${wall}?servers=${BROKEN_SOURCE}&interval=600`);
    await statusShown(page, "Failed to fetch");
    await expect(page.locator(ERROR_ICON)).toBeVisible({ timeout: resolveTimeout(30_000) });
    await expect(page.locator(STATUS_ICONS)).toHaveCSS("opacity", "1");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await expect(page.locator(HTML)).toHaveAttribute("data-bs-theme", mode);
      await assertToken(page, ERROR_ICON, "color", "--design-danger", `error marker ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [STATUS], "fediwall failing source");
  });

  test("design: the settings dialog takes panel, fields and the primary action from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openWall(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await gotoOnion(page, seeded());
      await wallSettled(page);
      await openDialog(page, "appearance");
      await assertToken(page, DIALOG, "background-color", "--design-surface-2", `dialog ${mode}`);
      await assertToken(page, "#configModal .modal-header", "border-bottom-color", "--design-border", `dialog divider ${mode}`);
      await assertToken(page, TITLE_FIELD, "border-top-color", "--design-border-strong", `field ${mode}`);
      await assertToken(page, TITLE_FIELD, "background-color", "--design-surface-2", `field ${mode}`);
      await assertToken(page, "#btab-appearance", "background-color", "--design-surface-2", `selected tab ${mode}`);
      await assertToken(page, "#btab-appearance", "border-bottom-color", "--design-surface-2", `selected tab ${mode}`);
      await assertToken(page, APPLY, "background-color", "--design-primary", `primary action ${mode}`);
      await assertToken(page, APPLY, "color", "--design-on-primary", `primary action ${mode}`);
      await page.locator(APPLY).hover();
      await assertToken(page, APPLY, "background-color", "--design-primary-hover", `hovered primary action ${mode}`);
      await assertToken(page, APPLY, "color", "--design-on-primary", `hovered primary action ${mode}`);
      await page.locator("#btab-advanced").hover();
      await assertToken(page, "#btab-advanced", "background-color", "--design-surface-hover", `hovered tab ${mode}`);
      await assertToken(page, "#btab-advanced", "border-top-color", "--design-border", `hovered tab ${mode}`);
      await page.locator(TITLE_FIELD).focus();
      await assertToken(page, TITLE_FIELD, "background-color", "--design-surface-2", `focused field ${mode}`);
      await assertToken(page, TITLE_FIELD, "border-top-color", "--design-link", `focused field ${mode}`);
      await page.locator("#btab-filter").click();
      await expect(page.locator(CHECKBOX)).toBeVisible();
      await expect(page.locator(CHECKBOX), `checkbox ${mode}`).toHaveCSS("appearance", "auto");
      expect(
        await page.locator(CHECKBOX).evaluate((element) => getComputedStyle(element).accentColor),
        `checkbox accent ${mode}`,
      ).toBe(await tokenValue(page, "--design-primary", "accent-color"));
      await page.locator(CHECKBOX).focus();
      await assertToken(page, CHECKBOX, "box-shadow", "--design-focus-ring", `focused checkbox ${mode}`);
      await page.locator(CHECKBOX).hover();
      await page.mouse.down();
      await expect(page.locator(CHECKBOX), `pressed checkbox ${mode}`).toHaveCSS("filter", "none");
      await page.mouse.up();
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, DIALOG, "fediwall dialog");
    await assertReadable(
      page,
      ["#configModal .modal-title", "#btab-filter", "#btab-content", "#ctab-filter .form-check-label", "#ctab-filter .form-text", APPLY],
      "fediwall dialog",
    );
    await page.locator("#btab-advanced").hover();
    await assertReadable(page, ["#btab-advanced"], "fediwall hovered tab");
  });

  test("design: a pinned post is marked with palette colors and stays readable", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openWall(page);
    await openCardMenu(page);
    await assertToken(page, CARD_MENU, "background-color", "--design-surface-2", "card menu");
    await page.locator(`${CARD_MENU} .dropdown-item`, { hasText: "Pin" }).click();
    await expect(page.locator(PINNED_HEADER)).toHaveCount(1);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await expect(page.locator(HTML)).toHaveAttribute("data-bs-theme", mode);
      await assertToken(page, PINNED_HEADER, "background-color", "--design-surface-active", `pinned post ${mode}`);
      expect(
        await page.locator(PINNED_HEADER).evaluate((element) => getComputedStyle(element).boxShadow),
        `pinned post marker ${mode}`,
      ).toContain(await tokenValue(page, "--design-primary", "color"));
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [`${PINNED_HEADER} .displayname`, `${PINNED_HEADER} .profile`], "fediwall pinned post");
  });

  test("design: the theme switch of the wall is respected and mirrored", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.emulateMedia({ colorScheme: "light" });
    await openWall(page);
    const html = page.locator(HTML);
    const surface = () => tokenValue(page, "--design-surface-1", "background-color");
    const lightSurface = await surface();
    await expect(html).toHaveAttribute("data-bs-theme", "light");
    await expect(html, "the palette follows the browser while the wall does").not.toHaveAttribute("data-design-theme");

    await page.locator(THEME_TOGGLE).click();
    await expect(html).toHaveAttribute("data-bs-theme", "dark");
    await expect(html).toHaveAttribute("data-design-theme", "dark");
    expect(await surface(), "a dark wall in a light browser must switch the tokens").not.toBe(lightSurface);
    await assertToken(page, "body", "background-color", "--design-surface-1", "dark wall in a light browser");
    await assertReadable(page, [STATUS, CARD_TEXT, DISPLAY_NAME], "dark wall in a light browser");

    await page.emulateMedia({ colorScheme: "light" });
    await page.locator(THEME_TOGGLE).click();
    await expect(html).toHaveAttribute("data-bs-theme", "light");
    await expect(html, "the light wall hands the mode back to the browser").not.toHaveAttribute("data-design-theme");

    await page.emulateMedia({ colorScheme: "dark" });
    await gotoOnion(page, seeded("&theme=light"));
    await wallSettled(page);
    await expect(html).toHaveAttribute("data-design-theme", "light");
    expect(await surface(), "a light wall in a dark browser must keep the light tokens").toBe(lightSurface);
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: the wall shows the generated icons and the configured title", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!faviconIcoUrl && !title, "logo and title replacement are disabled for this role");
    await openWall(page);
    if (title) {
      await expect
        .poll(async () => (await page.title()).split(title).length - 1, {
          message: "the title of the wall must carry the configured title exactly once",
        })
        .toBe(1);
    }
    if (faviconIcoUrl) {
      const icons = [
        ["image/png", faviconPngUrl],
        ["image/svg+xml", faviconSvgUrl],
        ["image/vnd.microsoft.icon", faviconIcoUrl],
      ];
      for (const [type, url] of icons) {
        await expect(page.locator(`link[rel~='icon'][type='${type}']`)).toHaveAttribute("href", url);
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

  test("design: the wall list takes its colors from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(shared.env.wallSlugs.length < 2, "a single wall is redirected to instead of listed");
    await gotoOnion(page, `${shared.env.appBaseUrl}/`);
    await expect(page.locator(WALL_LINK).first()).toBeVisible({ timeout: resolveTimeout(60_000) });
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "body", "background-color", "--design-surface-1", `wall list ${mode}`);
      await assertToken(page, "h1", "color", "--design-text", `wall list heading ${mode}`);
      await assertToken(page, WALL_LINK, "background-color", "--design-surface-2", `wall link ${mode}`);
      await assertToken(page, WALL_LINK, "color", "--design-link", `wall link ${mode}`);
      await assertToken(page, WALL_LINK, "border-top-color", "--design-border-strong", `wall link ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, ["h1", WALL_LINK], "fediwall wall list");
  });

  function galleryViews() {
    const dialog = (name, tab, query = "") => ({
      name,
      url: seeded(query),
      prepare: async (page) => {
        await wallSettled(page);
        await openDialog(page, tab);
      },
    });
    const views = [
      { name: "wall", url: seeded(), prepare: wallSettled },
      { name: "wall-tags", url: seeded("&tags=fediverse,opensource,selfhosting"), prepare: wallSettled },
      {
        name: "wall-accounts",
        url: seeded(`&accounts=biber@${SOURCE},ada@${SOURCE},grace@${SOURCE}`),
        prepare: wallSettled,
      },
      { name: "wall-text-only", url: seeded("&media=no"), prepare: wallSettled },
      { name: "wall-media-only", url: seeded("&text=no"), prepare: wallSettled },
      { name: "wall-forced-dark", url: seeded("&theme=dark"), prepare: wallSettled },
      { name: "wall-forced-light", url: seeded("&theme=light"), prepare: wallSettled },
      {
        name: "wall-empty",
        url: `${wall}?servers=${QUIET_SOURCE}&interval=600`,
        prepare: (page) => statusShown(page, "OK"),
      },
      {
        name: "wall-error",
        url: `${wall}?servers=${BROKEN_SOURCE}&interval=600`,
        prepare: async (page) => {
          await statusShown(page, "Failed to fetch");
          await expect(page.locator(ERROR_ICON)).toBeVisible({ timeout: resolveTimeout(30_000) });
        },
      },
      {
        name: "wall-footer",
        url: seeded(),
        prepare: async (page) => {
          await wallSettled(page);
          await page.locator(FOOTER).scrollIntoViewIfNeeded();
        },
      },
      {
        name: "footer-focus",
        url: `${wall}?servers=${QUIET_SOURCE}&interval=600`,
        prepare: async (page) => {
          await statusShown(page, "OK");
          await page.locator(CUSTOMIZE).focus();
          await page.keyboard.press("Shift+Tab");
          await expect(page.locator(THEME_TOGGLE)).toBeFocused();
        },
      },
      {
        name: "footer-button-hover",
        url: `${wall}?servers=${QUIET_SOURCE}&interval=600`,
        prepare: async (page) => {
          await statusShown(page, "OK");
          await page.locator(CUSTOMIZE).hover();
        },
      },
      {
        name: "info-bar-hover",
        url: seeded("&tags=fediverse"),
        prepare: async (page) => {
          await wallSettled(page);
          await page.locator(INFO_BAR).hover();
          await expect(page.locator(`${INFO_BAR} .secret`)).toHaveCSS("opacity", "1");
        },
      },
      {
        name: "card-hover",
        url: seeded(),
        prepare: async (page) => {
          await wallSettled(page);
          await page.locator(CARD).first().hover();
          await expect(page.locator(".wall-item .secret").first()).toHaveCSS("opacity", "1");
        },
      },
      {
        name: "card-menu",
        url: seeded(),
        prepare: async (page) => {
          await openCardMenu(page);
          await scrolledToTop(page);
        },
      },
      {
        name: "card-menu-item-hover",
        url: seeded(),
        prepare: async (page) => {
          await openCardMenu(page);
          await page.locator(`${CARD_MENU} .dropdown-item`).nth(1).hover();
        },
      },
      {
        name: "card-pinned",
        url: seeded(),
        prepare: async (page) => {
          await openCardMenu(page);
          await page.locator(`${CARD_MENU} .dropdown-item`, { hasText: "Pin" }).click();
          await expect(page.locator(PINNED_HEADER)).toHaveCount(1);
          await wallSettled(page);
          await scrolledToTop(page);
        },
      },
      dialog("settings-content"),
      {
        name: "settings-content-no-source",
        url: `${wall}?servers=&interval=600`,
        prepare: async (page) => {
          await openDialog(page);
          await expect(page.locator("#edit-tags")).toBeDisabled();
        },
      },
      {
        name: "settings-field-focus",
        url: seeded(),
        prepare: async (page) => {
          await wallSettled(page);
          await openDialog(page);
          await page.locator(SOURCES_FIELD).click();
        },
      },
      dialog("settings-filter", "filter"),
      dialog("settings-appearance", "appearance"),
      dialog("settings-advanced", "advanced"),
      {
        name: "settings-tab-hover",
        url: seeded(),
        prepare: async (page) => {
          await wallSettled(page);
          await openDialog(page);
          await page.locator("#btab-advanced").hover();
        },
      },
      {
        name: "settings-rate-limit-warning",
        url: `${wall}?servers=${SOURCE}&tags=a1,b2,c3,d4,e5,f6&interval=5`,
        prepare: async (page) => {
          await wallSettled(page);
          await openDialog(page);
          await expect(page.locator("#configModal .alert-warning")).toBeVisible({ timeout: resolveTimeout(30_000) });
          await page.locator(APPLY).scrollIntoViewIfNeeded();
        },
      },
    ];
    if (shared.env.wallSlugs.length > 1) {
      views.push({
        name: "wall-list",
        url: `${shared.env.appBaseUrl}/`,
        prepare: (page) => expect(page.locator(WALL_LINK).first()).toBeVisible(),
      });
    }
    return views;
  }

  test("design: gallery of wall states, card menus and the settings dialog", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(1_800_000));
    await page.addInitScript(installFediverseFixture, { quiet: QUIET_SOURCE, broken: BROKEN_SOURCE });
    await captureDesignGallery(page, galleryViews());
  });
};
