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
const { apiGetOnion, decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const base = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");
const showcase = process.env.CHESS_SHOWCASE_ENABLED === "true";
const liveGame = requireDotenvValue(process.env.CHESS_SHOWCASE_LIVE_GAME, "CHESS_SHOWCASE_LIVE_GAME");
const mateGame = requireDotenvValue(process.env.CHESS_SHOWCASE_MATE_GAME, "CHESS_SHOWCASE_MATE_GAME");
const freshGame = requireDotenvValue(process.env.CHESS_SHOWCASE_FRESH_GAME, "CHESS_SHOWCASE_FRESH_GAME");
const prefix = requireDotenvValue(process.env.CHESS_SHOWCASE_PREFIX, "CHESS_SHOWCASE_PREFIX");

const MODES = ["light", "dark"];
const USAGE = "ol.usage";
const USAGE_LINK = "ol.usage > li > p a";
const SAMPLE = "ol.usage pre";
const BOARD_LIST = "ul.challenge-board";
const CHALLENGER = "ul.challenge-board li > a:not(.challenge)";
const CHALLENGE = "ul.challenge-board a.challenge";
const RECENT = "table.recent-games";
const RECENT_LINK = "table.recent-games td a";
const MOVES = "blockquote.moves";
const MOVE = "blockquote.moves a.move";
const NOTE = "blockquote";
const BOARD = "p.chessboard img";
const FEN = "p.small.align-center code";
const PAGER = "div.pagination";
const PREVIOUS = "div.pagination p.align-left a";

const gameUrl = (id) => `${base}/games/${id}`;
const noteUrl = (key, ply) => `${base}/objects/${prefix}-${key}-${String(ply).padStart(2, "0")}`;

function requireShowcase() {
  test.skip(!showcase, "the showcase games are seeded on development deploys with design enabled only");
}

async function homeReady(page) {
  await expect(page.locator(USAGE)).toBeVisible({ timeout: resolveTimeout(10_000) });
  await expect(page.locator(CHALLENGE).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
  await expect(page.locator(RECENT_LINK).first()).toBeVisible({ timeout: resolveTimeout(10_000) });
}

async function boardReady(page) {
  const board = page.locator(BOARD);
  await expect(board).toBeVisible({ timeout: resolveTimeout(10_000) });
  await expect
    .poll(() => board.evaluate((image) => image.complete && image.naturalWidth > 0), {
      message: "the board drawing must load",
      timeout: resolveTimeout(10_000),
    })
    .toBe(true);
}

async function gameReady(page) {
  await expect(page.locator(MOVES)).toBeVisible({ timeout: resolveTimeout(10_000) });
  await boardReady(page);
}

async function noteReady(page) {
  await expect(page.locator(PAGER)).toBeVisible({ timeout: resolveTimeout(10_000) });
  await boardReady(page);
}

async function center(page, selector) {
  await page
    .locator(selector)
    .first()
    .evaluate((element) => element.scrollIntoView({ behavior: "instant", block: "center" }));
}

async function focusByKeyboard(page, locator) {
  await page.keyboard.press("Tab");
  await locator.focus();
}

async function linkTint(page) {
  return page.evaluate(() => {
    const probe = document.createElement("span");
    probe.style.setProperty("background-color", "color-mix(in srgb, var(--design-link) 5%, transparent)");
    document.body.appendChild(probe);
    const value = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return value;
  });
}

exports.register = function () {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await gotoOnion(page, `${base}/`);
    await expect(page.locator(USAGE)).toBeVisible({ timeout: resolveTimeout(10_000) });
    await assertDesignTokens(page, "chess");
  });

  test("design: the showcase fills the challenge board, the recent games and three game pages", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    requireShowcase();
    await gotoOnion(page, `${base}/`);
    await homeReady(page);
    await expect(page.locator(CHALLENGER), "three seeded challengers").toHaveCount(3);
    await expect(page.locator(CHALLENGE), "every seeded challenger carries a challenge link").toHaveCount(3);
    const games = await page.locator(RECENT_LINK).evaluateAll((links) => links.map((link) => link.getAttribute("href")));
    expect(games, "the recent games list both seeded games with more than six plies").toEqual(
      expect.arrayContaining([`/games/${liveGame}`, `/games/${mateGame}`]),
    );
    await expect(
      page.locator(`${RECENT} .time`).first(),
      "the app's inline script still converts the UTC times next to the injected design script",
    ).not.toContainText("GMT");
    for (const id of [liveGame, mateGame, freshGame]) {
      await gotoOnion(page, gameUrl(id));
      await gameReady(page);
    }
    await expect(page.locator(MOVE), "the fresh game has no moves yet").toHaveCount(0);
  });

  test("design: the front page takes page, text, links and sample panels from the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    requireShowcase();
    await gotoOnion(page, `${base}/`);
    await homeReady(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "body", "background-color", "--design-surface-1", `page ${mode}`);
      await assertToken(page, "body", "color", "--design-text", `page ${mode}`);
      await assertToken(page, USAGE_LINK, "color", "--design-link", `usage link ${mode}`);
      await assertToken(page, RECENT_LINK, "color", "--design-link", `recent game link ${mode}`);
      await assertToken(page, CHALLENGER, "color", "--design-link", `challenger link ${mode}`);
      await expect(page.locator(USAGE_LINK).first(), `usage link tint ${mode}`).toHaveCSS(
        "background-color",
        await linkTint(page),
      );
      await expect(page.locator(CHALLENGE).first(), `challenge link ${mode}: no tint`).toHaveCSS(
        "background-color",
        "rgba(0, 0, 0, 0)",
      );
      await assertToken(page, SAMPLE, "background-color", "--design-surface-2", `sample ${mode}`);
      await assertToken(page, SAMPLE, "border-top-color", "--design-border", `sample divider ${mode}`);
      await assertToken(page, SAMPLE, "color", "--design-text", `sample ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, SAMPLE, "chess sample panel");
    await assertReadable(
      page,
      [
        "h1",
        `${USAGE} > li > p`,
        USAGE_LINK,
        SAMPLE,
        `${USAGE} ul.small li`,
        CHALLENGER,
        RECENT_LINK,
        `${RECENT} .time`,
        "p.small.align-right a",
      ],
      "chess front page",
    );
    await page.locator(RECENT_LINK).first().hover();
    await assertReadable(page, [RECENT_LINK], "chess hovered game link");
  });

  test("design: a keyboard focus stop draws its indicator in the link tone", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    requireShowcase();
    await gotoOnion(page, `${base}/`);
    await homeReady(page);
    const expected = await tokenValue(page, "--design-link", "color");
    for (const selector of [USAGE_LINK, RECENT_LINK]) {
      const link = page.locator(selector).first();
      await focusByKeyboard(page, link);
      const outline = await link.evaluate((element) => {
        const style = getComputedStyle(element);
        return { color: style.outlineColor, style: style.outlineStyle, width: parseFloat(style.outlineWidth) };
      });
      expect(outline.style, `a focused '${selector}' must draw an outline`).not.toBe("none");
      expect(outline.width, `a focused '${selector}' must draw an outline`).toBeGreaterThan(0);
      expect(outline.color, `the outline of '${selector}' takes --design-link`).toBe(expected);
    }
  });

  test("design: a game page frames the moves and keeps the board drawing as content", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    requireShowcase();
    await gotoOnion(page, gameUrl(liveGame));
    await gameReady(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, MOVES, "background-color", "--design-surface-2", `moves ${mode}`);
      await assertToken(page, MOVES, "border-top-color", "--design-border", `moves divider ${mode}`);
      await assertToken(page, MOVE, "color", "--design-link", `move link ${mode}`);
      await assertToken(page, BOARD, "border-top-color", "--design-border", `board border ${mode}`);
      await expect(page.locator(BOARD), `board ${mode}: no filter on content`).toHaveCSS("filter", "none");
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, MOVES, "chess moves panel");
    await assertReadable(page, ["h3", MOVES, MOVE, "p.small.align-right", FEN], "chess game page");
    const size = await page.locator(BOARD).evaluate((image) => [image.naturalWidth, image.naturalHeight]);
    expect(size[0], "the board drawing is the app's own square raster").toBe(size[1]);
    expect(size[0], "the board drawing is the app's own raster").toBeGreaterThan(0);
  });

  test("design: a move note frames the King's reply and its pager", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    requireShowcase();
    await gotoOnion(page, noteUrl("live", 10));
    await noteReady(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, NOTE, "background-color", "--design-surface-2", `note ${mode}`);
      await assertToken(page, NOTE, "border-top-color", "--design-border", `note divider ${mode}`);
      await assertToken(page, PREVIOUS, "color", "--design-link", `pager link ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, NOTE, "chess move note");
    await assertReadable(page, ["h3", NOTE, `${NOTE} a.mention`, `${PAGER} a`, FEN], "chess move note");
  });

  test("design: every page carries the configured favicon and title", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    requireShowcase();
    test.skip(!faviconUrl && !title, "logo and title replacement are disabled for this role");
    for (const url of [`${base}/`, gameUrl(liveGame), noteUrl("mate", 7)]) {
      await gotoOnion(page, url);
      await expect(page.locator("body")).toBeVisible({ timeout: resolveTimeout(10_000) });
      if (title) {
        await expect.poll(() => page.title(), { message: `${url} carries the configured title` }).toContain(title);
      }
      if (faviconUrl) {
        await expect(page.locator("link[rel~='icon']")).toHaveCount(1);
        await expect(page.locator("link[rel~='icon']")).toHaveAttribute("href", faviconUrl);
      }
    }
    if (faviconUrl) {
      const served = await apiGetOnion(page.request, faviconUrl);
      expect(served.status(), "the favicon must be served").toBe(200);
      expect(served.headers()["content-type"] || "", "the favicon is a PNG").toContain("image/png");
    }
  });

  function galleryViews() {
    const home = (name, prepare) => ({ name, url: `${base}/`, prepare });
    const game = (name, id, prepare) => ({ name, url: gameUrl(id), prepare });
    const note = (name, key, ply, prepare = noteReady) => ({ name, url: noteUrl(key, ply), prepare });
    return [
      home("home", homeReady),
      home("home-samples", async (page) => {
        await homeReady(page);
        await center(page, SAMPLE);
      }),
      home("home-challenge-board", async (page) => {
        await homeReady(page);
        await center(page, BOARD_LIST);
      }),
      home("home-recent-games", async (page) => {
        await homeReady(page);
        await center(page, RECENT);
      }),
      home("home-credits", async (page) => {
        await homeReady(page);
        await page.evaluate(() => window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "instant" }));
      }),
      home("home-link-hover", async (page) => {
        await homeReady(page);
        await page.locator(USAGE_LINK).first().hover();
      }),
      home("home-link-focus", async (page) => {
        await homeReady(page);
        await focusByKeyboard(page, page.locator(USAGE_LINK).first());
      }),
      home("home-challenge-hover", async (page) => {
        await homeReady(page);
        await center(page, BOARD_LIST);
        await page.locator(CHALLENGE).first().hover();
      }),
      home("home-recent-game-hover", async (page) => {
        await homeReady(page);
        await center(page, RECENT);
        await page.locator(RECENT_LINK).first().hover();
      }),
      game("game-in-progress", liveGame, gameReady),
      game("game-moves", liveGame, async (page) => {
        await gameReady(page);
        await center(page, MOVES);
      }),
      game("game-board", liveGame, async (page) => {
        await gameReady(page);
        await center(page, BOARD);
      }),
      game("game-fen", liveGame, async (page) => {
        await gameReady(page);
        await center(page, FEN);
      }),
      game("game-move-hover", liveGame, async (page) => {
        await gameReady(page);
        await page.locator(MOVE).nth(2).hover();
      }),
      game("game-move-focus", liveGame, async (page) => {
        await gameReady(page);
        await focusByKeyboard(page, page.locator(MOVE).nth(3));
      }),
      game("game-finished", mateGame, gameReady),
      game("game-new", freshGame, gameReady),
      note("note-setup", "live", 0),
      note("note-opening", "live", 1),
      note("note-capture", "live", 10),
      note("note-check", "live", 12),
      note("note-checkmate", "mate", 7),
      note("note-pager-hover", "live", 10, async (page) => {
        await noteReady(page);
        await page.locator(PREVIOUS).hover();
      }),
    ];
  }

  test("design: gallery of the front page, game pages and move notes", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    requireShowcase();
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(1_200_000));
    await captureDesignGallery(page, galleryViews());
  });
};
