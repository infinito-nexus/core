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
const { decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, performKeycloakLoginForm } = require("./personas");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const MODES = ["light", "dark"];
const FOCUS_WALK_LIMIT = 10;
const SHOWN_BASE_MS = 30_000;
const ROOM = "design-showcase";
const QUIET =
  "config.disableInitialGUM=true&config.startWithAudioMuted=true&config.startWithVideoMuted=true" +
  "&config.hideConferenceTimer=true&config.notifications=[]";
const JOIN = `#config.prejoinConfig.enabled=false&config.toolbarConfig.alwaysVisible=true&${QUIET}&userInfo.displayName=%22Design%22`;
const PREJOIN = `#${QUIET}`;
const ROOM_FIELD = "#enter_room_field";
const START = "#enter_room_button";
const HEADER = ".welcome .header";
const ENTER_BOX = ".welcome .header #enter_room .join-meeting-container";
const FRAME =".welcome .header, .welcome .welcome-footer";
const CARD = ".welcome .welcome-card";
const LOGO = ".welcome .welcome-watermark div.watermark";
const SETTINGS = ".welcome-page-settings .toolbox-icon";
const JOIN_BUTTON = '[data-testid="prejoin.joinMeeting"]';
const JOIN_OPTIONS = '[data-testid="prejoin.joinOptions"]';
const NAME_FIELD = "#premeeting-name-input";
const PREMEETING = ".premeeting-screen";
const TOOLBOX = "#new-toolbox .toolbox-content-items";
const TOOLBOX_ICON = "#new-toolbox .toolbox-button:not(.disabled) .toolbox-icon svg";
const HANGUP = "#new-toolbox .hangup-button, #new-toolbox .hangup-menu-button";
const HANGUP_MENU = "#new-toolbox .hangup-menu-button";
const MORE = '#new-toolbox [aria-label="More actions"]';
const MENU = "#overflow-context-menu, [class*='-drawerMenuContainer']";
const MENU_GROUP =
  "#overflow-context-menu [class*='-contextMenuItemGroup'] + [class*='-contextMenuItemGroup']";
const MENU_ITEM = "#overflow-context-menu [class*='-contextMenuItem']";
const DIALOG = "[role='dialog'][class*='-modal']";
const CONFIRM = "#modal-dialog-ok-button";
const DESTRUCTIVE = "button[class*='-button-destructive-']";
const SELECTED_TAB = `${DIALOG} [role='tab'][aria-selected='true']`;
const CHAT = "#sideToolbarContainer";
const PARTICIPANTS = "#participants-pane";

const base = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");

async function shown(page, selector, base = SHOWN_BASE_MS) {
  await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(base) });
}

async function joined(page) {
  await shown(page, TOOLBOX);
  await expect
    .poll(() => page.evaluate(() => Boolean(window.APP?.conference?.isJoined?.())), {
      timeout: resolveTimeout(60_000),
      message: "the conference must be joined",
    })
    .toBe(true);
}

async function open(page, path, ready) {
  const url = `${base}/${path}`;
  await gotoOnion(page, url);
  if (isServiceEnabled("sso") && page.url().includes("openid-connect/auth")) {
    await performKeycloakLoginForm(page, adminUsername, adminPassword);
    await expect
      .poll(
        () => {
          const current = new URL(page.url());
          return current.host === new URL(base).host && !current.pathname.startsWith("/oauth2/");
        },
        { timeout: resolveTimeout(90_000), message: "the sign-in must return to Jitsi" },
      )
      .toBe(true);
    await gotoOnion(page, url);
  }
  await shown(page, ready, 60_000);
}

async function inBothModes(page, check) {
  for (const mode of MODES) {
    await page.emulateMedia({ colorScheme: mode });
    await check(mode);
  }
  await page.emulateMedia({ colorScheme: null });
}

async function settled(page, selector) {
  await expect
    .poll(
      () =>
        page
          .locator(selector)
          .first()
          .evaluate(
            (element) =>
              getComputedStyle(element).opacity === "1" &&
              element
                .getAnimations({ subtree: true })
                .every(
                  (animation) =>
                    animation.playState !== "running" || animation.effect?.getComputedTiming().iterations === Infinity,
                ),
          ),
      { timeout: resolveTimeout(15_000), message: `${selector} must finish opening` },
    )
    .toBe(true);
}

async function loads(page, url) {
  return page.evaluate(
    (src) =>
      new Promise((resolve) => {
        const image = new Image();
        image.onload = () => resolve(image.naturalWidth > 0);
        image.onerror = () => resolve(false);
        image.src = src;
      }),
    url,
  );
}

async function branding(page) {
  return page.evaluate(() => {
    const state = window.APP.store.getState()["features/dynamic-branding"];
    return { ready: state.customizationReady, failed: state.customizationFailed, themed: Boolean(state.muiBrandedTheme) };
  });
}

async function focusStop(page) {
  return page.evaluate((frame) => {
    const element = document.activeElement;
    const style = getComputedStyle(element);
    return {
      name: [element.tagName.toLowerCase(), ...element.classList].join("."),
      framed: Boolean(element.closest(frame)) && !element.closest(".join-meeting-container"),
      color: style.outlineStyle === "none" || parseFloat(style.outlineWidth) === 0 ? "none" : style.outlineColor,
    };
  }, FRAME);
}

async function fresh(page, url) {
  if (await page.evaluate(() => window.designViewSeen === true)) {
    await gotoOnion(page, "about:blank");
    await gotoOnion(page, url);
  }
  await page.evaluate(() => {
    window.designViewSeen = true;
  });
}

function views() {
  const view = (name, path, ready, extra) => {
    const url = `${base}/${path}`;
    return {
      name,
      url,
      prepare: async (page) => {
        await fresh(page, url);
        await shown(page, ready);
        if (extra) await extra(page);
      },
    };
  };
  const press = (key) => (page) => page.keyboard.press(key);
  const click = (selector) => (page) => page.locator(selector).first().click({ timeout: resolveTimeout(10_000) });
  const panel = (trigger, selector, extra) => async (page) => {
    await trigger(page);
    await shown(page, selector, 10_000);
    await settled(page, selector);
    if (extra) await extra(page);
  };
  const fromMenu = (label) => async (page) => {
    const direct = page.locator(`${TOOLBOX} [aria-label="${label}"]`).first();
    if (await direct.isVisible()) {
      await direct.click({ timeout: resolveTimeout(10_000) });
      return;
    }
    await page.locator(MORE).first().click({ timeout: resolveTimeout(10_000) });
    await page.locator(`[aria-label="${label}"]`).last().click({ timeout: resolveTimeout(10_000) });
  };
  const conference = (name, extra) =>
    view(name, `${ROOM}${JOIN}`, TOOLBOX, async (page) => {
      await joined(page);
      if (extra) await extra(page);
    });
  return [
    view("welcome", "", ROOM_FIELD),
    view("welcome-field-focus", "", ROOM_FIELD, async (page) => {
      await page.locator(ROOM_FIELD).fill("design-showcase");
      await page.locator(ROOM_FIELD).focus();
    }),
    view("welcome-invalid-name", "", ROOM_FIELD, async (page) => {
      await page.locator(ROOM_FIELD).fill("a?b");
      await shown(page, ".not-allow-title-character-div", 10_000);
    }),
    view("welcome-recent-hover", "", ".meetings-list", async (page) => {
      await page.locator(".meetings-list .item").first().hover({ timeout: resolveTimeout(10_000) });
    }),
    view("welcome-settings", "", ROOM_FIELD, panel(click(SETTINGS), DIALOG)),
    view("prejoin", `${ROOM}-prejoin${PREJOIN}`, JOIN_BUTTON),
    view("prejoin-join-options", `${ROOM}-options${PREJOIN}`, JOIN_BUTTON, async (page) => {
      await page.locator(NAME_FIELD).fill("", { timeout: resolveTimeout(10_000) });
      await page.locator(JOIN_OPTIONS).click({ timeout: resolveTimeout(10_000) });
      await shown(page, '[data-testid="prejoin.joinWithoutAudio"]', 10_000);
    }),
    conference("conference"),
    conference("conference-more-actions", panel(click(MORE), MENU)),
    conference(
      "conference-chat",
      panel(press("c"), CHAT, async (page) => {
        const field = page.locator(`${CHAT} textarea`).first();
        if (!(await field.isVisible())) return;
        await field.fill("Design showcase", { timeout: resolveTimeout(10_000) });
        await field.press("Enter", { timeout: resolveTimeout(10_000) });
        await expect(field).toHaveValue("", { timeout: resolveTimeout(10_000) });
      }),
    ),
    conference("conference-participants", panel(press("p"), PARTICIPANTS)),
    conference("conference-speaker-stats", panel(press("t"), DIALOG)),
    conference("conference-video-quality", panel(press("a"), DIALOG)),
    conference("conference-shortcuts", panel(press("?"), DIALOG)),
    conference("conference-settings", panel(fromMenu("Open settings"), DIALOG)),
    conference("conference-profile", panel(fromMenu("Edit your profile"), DIALOG)),
    conference("conference-invite", panel(fromMenu("Invite people"), DIALOG)),
    conference("conference-security", panel(fromMenu("Security options"), DIALOG)),
    view("page-close", "static/close.html", ".redirectPageMessage"),
    view("page-not-found", "static/404.html", ".error_page"),
    view("page-browser", "static/recommendedBrowsers.html", ".unsupported-desktop-browser"),
  ];
}

exports.register = function () {
  test.describe("corporate design", () => {
    test.use({ serviceWorkers: "block" });

    test("design: the tokens are present and switch between light and dark", async ({ page }) => {
      skipUnlessServiceEnabled("design");
      await open(page, "", ROOM_FIELD);
      await assertDesignTokens(page, "Jitsi welcome page");
    });

    test("design: the welcome page follows the palette", async ({ page }) => {
      skipUnlessServiceEnabled("design");
      await open(page, "", ROOM_FIELD);
      await inBothModes(page, async (mode) => {
        await page.locator(CARD).hover();
        await assertToken(page, ".welcome", "background-color", "--design-surface-1", `page ${mode}`);
        await assertToken(page, HEADER, "background-color", "--design-frame", `header ${mode}`);
        await assertToken(page, `${HEADER} .header-text-title`, "color", "--design-on-frame", `header title ${mode}`);
        await assertToken(page, ".welcome .welcome-footer", "background-color", "--design-frame", `footer ${mode}`);
        await assertToken(page, ROOM_FIELD, "background-color", "--design-surface-2", `room field ${mode}`);
        await assertToken(page, ROOM_FIELD, "color", "--design-text", `room field ${mode}`);
        await assertToken(page, CARD, "background-color", "--design-surface-3", `card ${mode}`);
        await assertToken(page, START, "background-color", "--design-primary", `start action ${mode}`);
        await assertToken(page, START, "color", "--design-on-primary", `start action ${mode}`);
        await page.locator(START).hover();
        await assertToken(page, START, "background-color", "--design-primary-hover", `hovered start action ${mode}`);
      });
      await page.locator(CARD).hover();
      await assertLightAndDark(page, CARD, "Jitsi welcome card");
      await assertLightAndDark(page, ".welcome .welcome-cards-container", "Jitsi welcome page");
      await assertReadable(
        page,
        [
          `${HEADER} .header-text-title`,
          `${HEADER} .header-text-subtitle`,
          ROOM_FIELD,
          START,
          ".welcome .welcome-footer-row-1-text",
          { selector: ".meetings-list .description", optional: true },
        ],
        "Jitsi welcome page",
      );
    });

    test("design: a narrow welcome page stacks field and action without a painted box", async ({ page }) => {
      skipUnlessServiceEnabled("design");
      await open(page, "", ROOM_FIELD);
      await assertToken(page, ENTER_BOX, "background-color", "--design-surface-2", "box around field and action");
      await page.setViewportSize({ width: 390, height: 844 });
      await expect(
        page.locator(ENTER_BOX),
        "the box must not be painted where upstream stacks field and action",
      ).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
      await assertToken(page, ROOM_FIELD, "background-color", "--design-surface-2", "narrow room field");
    });

    test("design: the app theme reads the tokens on the prejoin screen", async ({ page }) => {
      skipUnlessServiceEnabled("design");
      await open(page, `${ROOM}-prejoin${PREJOIN}`, JOIN_BUTTON);
      await expect
        .poll(() => branding(page), {
          timeout: resolveTimeout(30_000),
          message: "the app must load the branding document and build its theme from it",
        })
        .toEqual({ ready: true, failed: false, themed: true });
      await inBothModes(page, async (mode) => {
        await page.locator(NAME_FIELD).hover();
        await assertToken(page, PREMEETING, "background-color", "--design-surface-2", `prejoin panel ${mode}`);
        await assertToken(page, "#preview", "background-color", "--design-surface-1", `preview ${mode}`);
        await assertToken(page, NAME_FIELD, "background-color", "--design-surface-3", `name field ${mode}`);
        await assertToken(page, NAME_FIELD, "color", "--design-text", `name field ${mode}`);
        await assertToken(page, JOIN_BUTTON, "background-color", "--design-primary", `join action ${mode}`);
        await assertToken(page, JOIN_BUTTON, "color", "--design-on-primary", `join action ${mode}`);
        await assertToken(page, "#preview .avatar", "color", "--design-on-frame", `avatar initials ${mode}`);
        await assertToken(page, "#preview .avatar", "background-color", "--design-frame", `avatar ${mode}`);
        await page.locator(JOIN_BUTTON).hover();
        await assertToken(page, JOIN_BUTTON, "background-color", "--design-primary-hover", `hovered join action ${mode}`);
      });
      await page.locator(NAME_FIELD).hover();
      await assertLightAndDark(page, PREMEETING, "Jitsi prejoin panel");
      await assertReadable(page, [JOIN_BUTTON, NAME_FIELD, `${PREMEETING} h1`, "#preview .avatar"], "Jitsi prejoin");
    });

    test("design: conference chrome, menu dividers and the leave action follow the palette", async ({ page }) => {
      skipUnlessServiceEnabled("design");
      await open(page, `${ROOM}-chrome${JOIN}`, TOOLBOX);
      await joined(page);
      await inBothModes(page, async (mode) => {
        await assertToken(page, "#largeVideoContainer", "background-color", "--design-surface-1", `stage ${mode}`);
        await assertToken(page, TOOLBOX, "background-color", "--design-surface-2", `toolbox ${mode}`);
        await assertToken(page, TOOLBOX_ICON, "fill", "--design-text", `toolbox icon ${mode}`);
        await assertToken(page, HANGUP, "background-color", "--design-danger", `leave action ${mode}`);
        await assertToken(page, `${HANGUP_MENU} svg, #new-toolbox .hangup-button svg`, "fill", "--design-on-danger", `leave action icon ${mode}`);
      });
      await assertLightAndDark(page, TOOLBOX, "Jitsi toolbox");
      await page.locator(MORE).first().click({ timeout: resolveTimeout(15_000) });
      await shown(page, MENU, 15_000);
      await settled(page, MENU);
      await inBothModes(page, async (mode) => {
        await assertToken(page, "#overflow-context-menu", "background-color", "--design-surface-2", `menu ${mode}`);
        await assertToken(page, MENU_GROUP, "border-top-color", "--design-border", `menu divider ${mode}`);
        await expect(page.locator(MENU_GROUP).first(), `the menu divider must be drawn ${mode}`).toHaveCSS(
          "border-top-width",
          "1px",
        );
      });
      await assertReadable(page, [MENU_ITEM], "Jitsi menu");
    });

    test("design: dialogs and their filled actions follow the palette", async ({ page }) => {
      skipUnlessServiceEnabled("design");
      await open(page, `${ROOM}-dialog${JOIN}`, TOOLBOX);
      await joined(page);
      await page.keyboard.press("?");
      await shown(page, DIALOG, 15_000);
      await settled(page, DIALOG);
      await inBothModes(page, async (mode) => {
        await page.locator(`${DIALOG} h1`).first().hover();
        await assertToken(page, DIALOG, "background-color", "--design-surface-2", `dialog ${mode}`);
        await assertToken(page, DIALOG, "color", "--design-text", `dialog ${mode}`);
        await assertToken(page, SELECTED_TAB, "background-color", "--design-surface-active", `selected tab ${mode}`);
        await assertToken(page, CONFIRM, "background-color", "--design-primary", `dialog action ${mode}`);
        await assertToken(page, CONFIRM, "color", "--design-on-primary", `dialog action ${mode}`);
        await page.locator(CONFIRM).hover();
        await assertToken(page, CONFIRM, "background-color", "--design-primary-hover", `hovered dialog action ${mode}`);
      });
      await page.locator(`${DIALOG} h1`).first().hover();
      await assertLightAndDark(page, DIALOG, "Jitsi dialog");
      await assertReadable(page, [`${DIALOG} h1`, SELECTED_TAB, CONFIRM, "#modal-dialog-cancel-button"], "Jitsi dialog");
    });

    test("design: the destructive action of the leave menu follows the palette", async ({ page }) => {
      skipUnlessServiceEnabled("design");
      await open(page, `${ROOM}-leave${JOIN}`, TOOLBOX);
      await joined(page);
      test.skip(
        (await page.locator(HANGUP_MENU).count()) === 0,
        "this participant may not end the meeting, so no destructive action is offered",
      );
      await page.locator(HANGUP_MENU).first().click({ timeout: resolveTimeout(15_000) });
      await shown(page, DESTRUCTIVE, 15_000);
      await inBothModes(page, async (mode) => {
        await assertToken(page, DESTRUCTIVE, "background-color", "--design-danger", `destructive action ${mode}`);
        await assertToken(page, DESTRUCTIVE, "color", "--design-on-danger", `destructive action ${mode}`);
      });
    });

    test("design: every focus stop inside the frame draws its indicator in on-frame", async ({ page }) => {
      skipUnlessServiceEnabled("design");
      await inBothModes(page, async (mode) => {
        await open(page, "", ROOM_FIELD);
        const ring = await tokenValue(page, "--design-on-frame", "color");
        const stops = new Set();
        for (let step = 0; step < FOCUS_WALK_LIMIT; step += 1) {
          await page.keyboard.press("Tab");
          const stop = await focusStop(page);
          if (!stop.framed) continue;
          stops.add(stop.name);
          expect(stop.color, `keyboard stop ${stop.name} ${mode}: the focus indicator must be on-frame`).toBe(ring);
        }
        expect(stops.size, `the keyboard walk must find stops inside the frame ${mode}`).toBeGreaterThanOrEqual(2);
      });
    });

    test("design: the interface shows the generated logo and the configured title", async ({ page }) => {
      skipUnlessServiceEnabled("design");
      test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");
      await open(page, "", ROOM_FIELD);
      if (title) await expect(page).toHaveTitle(title);
      if (logoUrl) {
        const logo = page.locator(LOGO).first();
        await expect(logo).toHaveCSS("background-image", `url("${logoUrl}")`);
        const box = await logo.boundingBox();
        expect(box.width, "upstream shows a wordmark, so the logo box must be wider than high").toBeGreaterThan(
          box.height * 1.5,
        );
        await assertToken(page, HEADER, "background-color", "--design-frame", "the logo sits on the frame");
        await expect(page.locator("link[rel~='icon']").first()).toHaveAttribute("href", faviconUrl);
        for (const url of [logoUrl, faviconUrl]) {
          expect(await loads(page, url), `the page must be allowed to load ${url}`).toBe(true);
        }
      }
      await open(page, `${ROOM}-title${JOIN}`, TOOLBOX);
      await joined(page);
      if (title) {
        await expect
          .poll(() => page.title(), { timeout: resolveTimeout(30_000), message: "the conference title must end with the app name" })
          .toMatch(new RegExp(`\\| ${title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`));
      }
      if (logoUrl) {
        await expect(page.locator("div.watermark.leftwatermark").first()).toHaveCSS("background-image", `url("${logoUrl}")`);
      }
    });

    test("design: gallery of welcome page, prejoin, conference, dialogs and static pages", async ({ page }) => {
      skipUnlessServiceEnabled("design");
      test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
      test.setTimeout(resolveTimeout(2_400_000));
      await open(page, `${ROOM}${JOIN}`, TOOLBOX);
      await joined(page);
      await captureDesignGallery(page, views());
    });
  });
};
