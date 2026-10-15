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

const base = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");
const faviconUrl = decodeDotenvQuotedValue(process.env.DESIGN_FAVICON_URL || "");

const MODES = ["light", "dark"];
const COUNTER = ".menu .counter";
const INPUT = 'input[name="new-item"]';
const ADD = ".add-item-button";
const REMOVE_ALL = ".remove-all-items-button";
const ROW = "li.menu-item";
const TOGGLE = ".light-dark-mode";
const TOGGLE_ICON = ".light-dark-mode img.moon-sun";
const WINNER = ".winner";
const CANVAS = ".roulette-wheel canvas";
const CREDITS = ".icons-authors";
const NAMES = [
  "Margherita",
  "Salad",
  "Spaghetti",
  "Lemonade",
  "Orange juice",
  "Fries",
  "Kebab",
  "Ramen",
  "Tacos",
  "Falafel",
  "Curry",
  "Sushi",
  "Pancakes",
  "Burrito",
  "Dumplings",
  "Gnocchi",
];
const LONG_NAMES = ["Quattro stagioni XXL", "Spaghetti carbonara!", "Fresh orange juices", "Grilled halloumi wrap"];
const FREEZE = "*, *::before, *::after { transition: none !important; }";
const WHEEL_DRAWS = "__designWheelDraws";
const SEGMENT_FILLS = [
  "--design-frame",
  "--design-info",
  "--design-warning",
  "--design-danger",
  "--design-success",
  "--design-primary",
  "--design-frame-hover",
  "--design-info-hover",
  "--design-warning-hover",
  "--design-danger-hover",
  "--design-success-hover",
  "--design-primary-hover",
  "--design-frame-active",
  "--design-info-active",
  "--design-warning-active",
  "--design-danger-active",
];
const LABEL_TOKENS = [
  "--design-on-frame",
  "--design-on-info",
  "--design-on-warning",
  "--design-on-danger",
  "--design-on-success",
  "--design-on-primary",
];

async function ready(page) {
  await expect(page.locator(COUNTER)).toHaveText(/^\d+\/16$/, { timeout: resolveTimeout(10_000) });
}

async function open(page) {
  await gotoOnion(page, `${base}/`);
  await ready(page);
}

async function add(page, names) {
  for (const name of names) {
    await page.locator(INPUT).fill(name);
    await page.locator(ADD).click();
  }
  await page.mouse.move(0, 0);
  await expect(page.locator(COUNTER)).toHaveText(`${names.length}/16`, { timeout: resolveTimeout(10_000) });
}

async function spin(page) {
  await page.locator(CANVAS).click();
  await page.clock.runFor(20_000);
  await expect(page.locator(WINNER)).toHaveText(/^Winner: /, { timeout: resolveTimeout(10_000) });
}

async function focusByKeyboard(page, locator) {
  await page.keyboard.press("Tab");
  await locator.focus();
}

async function toggleTheme(page) {
  await page.locator(TOGGLE).click();
  await expect(page.locator("html")).toHaveAttribute("data-design-theme", /^(light|dark)$/, {
    timeout: resolveTimeout(10_000),
  });
}

async function rowContrasts(page) {
  return page.locator(ROW).evaluateAll((rows) => {
    const ctx = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
    const rgba = (value) => {
      ctx.clearRect(0, 0, 1, 1);
      ctx.fillStyle = "#000";
      ctx.fillStyle = value;
      ctx.fillRect(0, 0, 1, 1);
      const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data;
      return [r, g, b, a / 255];
    };
    const over = ([r, g, b, a], below) => [r, g, b].map((channel, i) => a * channel + (1 - a) * below[i]);
    const luminance = (rgb) => {
      const [r, g, b] = rgb.map((channel) => {
        const s = channel / 255;
        return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const surface = rgba(getComputedStyle(document.body).backgroundColor);
    return rows.map((row) => {
      const style = getComputedStyle(row);
      const tint = (style.boxShadow.match(/^(?:rgba?|color)\([^)]*\)/) || ["transparent"])[0];
      const fill = over(rgba(tint), over(rgba(style.backgroundColor), surface));
      const [fg, bg] = [luminance(over(rgba(style.color), fill)), luminance(fill)];
      return { row: row.textContent.trim(), ratio: (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05) };
    });
  });
}

async function logWheel(page) {
  await page.addInitScript((key) => {
    const proto = CanvasRenderingContext2D.prototype;
    const draws = (window[key] = []);
    for (const name of ["clearRect", "fill", "fillText"]) {
      const native = proto[name];
      proto[name] = function (...args) {
        if (this.canvas?.closest?.(".roulette-wheel")) {
          if (name === "clearRect") draws.length = 0;
          else draws.push({ name, color: String(this.fillStyle), text: name === "fillText" ? String(args[0]) : "" });
        }
        return native.apply(this, args);
      };
    }
  }, WHEEL_DRAWS);
}

async function wheelLabels(page) {
  return page.evaluate((key) => {
    const ctx = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
    const rgba = (value) => {
      ctx.clearRect(0, 0, 1, 1);
      ctx.fillStyle = "#000";
      ctx.fillStyle = value;
      ctx.fillRect(0, 0, 1, 1);
      const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data;
      return [r, g, b, a / 255];
    };
    const over = ([r, g, b, a], below) => [r, g, b].map((channel, i) => a * channel + (1 - a) * below[i]);
    const luminance = (rgb) => {
      const [r, g, b] = rgb.map((channel) => {
        const s = channel / 255;
        return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const surface = rgba(getComputedStyle(document.body).backgroundColor);
    const labels = [];
    let segment = null;
    for (const draw of window[key]) {
      if (draw.name === "fill") {
        segment = draw.color;
        continue;
      }
      const fill = over(rgba(segment), surface);
      const [fg, bg] = [luminance(over(rgba(draw.color), fill)), luminance(fill)];
      labels.push({ label: draw.text, color: draw.color, segment, ratio: (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05) });
    }
    return labels;
  }, WHEEL_DRAWS);
}

async function canvasColors(page, names) {
  return page.evaluate((tokens) => {
    const ctx = document.createElement("canvas").getContext("2d");
    return tokens.map((token) => {
      const probe = document.createElement("span");
      probe.style.color = `var(${token})`;
      document.body.appendChild(probe);
      ctx.fillStyle = getComputedStyle(probe).color;
      probe.remove();
      return ctx.fillStyle;
    });
  }, names);
}

async function rowFills(page) {
  return page.locator(ROW).evaluateAll((rows) => {
    const ctx = document.createElement("canvas").getContext("2d");
    return rows.map((row) => {
      ctx.fillStyle = (getComputedStyle(row).boxShadow.match(/^(?:rgba?|color)\([^)]*\)/) || ["transparent"])[0];
      return ctx.fillStyle;
    });
  });
}

exports.register = function () {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await open(page);
    await assertDesignTokens(page, "roulette wheel");
  });

  test("design: page, text, field, buttons and list rows take the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await open(page);
    await add(page, NAMES.slice(0, 3));
    await page.addStyleTag({ content: FREEZE });
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "body", "background-color", "--design-surface-1", `page ${mode}`);
      await assertToken(page, "body", "color", "--design-text", `text ${mode}`);
      await assertToken(page, INPUT, "background-color", "--design-surface-2", `field ${mode}`);
      await assertToken(page, INPUT, "border-top-color", "--design-border-strong", `field border ${mode}`);
      for (const [selector, label] of [
        [ADD, "add"],
        [REMOVE_ALL, "remove all"],
      ]) {
        await assertToken(page, selector, "background-color", "--design-primary", `${label} ${mode}`);
        await assertToken(page, selector, "color", "--design-on-primary", `${label} text ${mode}`);
        await assertToken(page, selector, "border-top-color", "--design-border-strong", `${label} border ${mode}`);
      }
      await assertToken(page, `${ROW} + ${ROW}`, "border-top-color", "--design-border", `row divider ${mode}`);
      await assertToken(page, "footer p", "color", "--design-text-muted", `credits toggle ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, COUNTER, "roulette wheel page");
    await assertReadable(page, [COUNTER, "label[for='new-item']", INPUT, ADD, REMOVE_ALL, "footer p"], "roulette wheel menu");
  });

  test("design: every row color keeps the item name readable in both modes", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await open(page);
    await add(page, NAMES);
    await page.addStyleTag({ content: FREEZE });
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      for (const { row, ratio } of await rowContrasts(page)) {
        expect(ratio, `row '${row}' reaches contrast ${ratio.toFixed(2)} in ${mode} mode (needs 4.5)`).toBeGreaterThanOrEqual(4.5);
      }
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: every wheel label reaches AA on its segment, and both come from tokens, in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await logWheel(page);
    await open(page);
    await add(page, NAMES);
    await page.addStyleTag({ content: FREEZE });
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await expect
        .poll(
          async () =>
            (await wheelLabels(page))
              .filter((entry) => entry.ratio < 4.5)
              .map((entry) => `${entry.label} ${entry.ratio.toFixed(2)}`),
          { message: `every wheel label reaches 4.5 on its segment in ${mode} mode` },
        )
        .toEqual([]);
    }
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      const fills = await canvasColors(page, SEGMENT_FILLS);
      await expect
        .poll(async () => (await wheelLabels(page)).map((entry) => entry.segment), {
          message: `the segments take the fill tokens in insertion order in ${mode} mode`,
        })
        .toEqual(fills);
      const labels = await canvasColors(page, LABEL_TOKENS);
      for (const entry of await wheelLabels(page)) {
        expect(labels, `the label '${entry.label}' takes an on-color token in ${mode} mode`).toContain(entry.color);
      }
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: the wheel repaints in the palette the native toggle picks, and every row shares its segment's fill", async ({
    page,
  }) => {
    skipUnlessServiceEnabled("design");
    await logWheel(page);
    await page.emulateMedia({ colorScheme: "light" });
    await open(page);
    await add(page, NAMES.slice(0, 6));
    await page.addStyleTag({ content: FREEZE });
    const before = (await wheelLabels(page)).map((entry) => entry.segment);
    expect(before, "the light wheel takes the light fill tokens").toEqual(
      await canvasColors(page, SEGMENT_FILLS.slice(0, 6)),
    );
    await toggleTheme(page);
    await expect(page.locator("html")).toHaveAttribute("data-design-theme", "dark");
    const fills = await canvasColors(page, SEGMENT_FILLS.slice(0, 6));
    expect(fills, "the toggle switches the fill tokens").not.toEqual(before);
    await expect
      .poll(async () => (await wheelLabels(page)).map((entry) => entry.segment), {
        message: "the wheel repaints in the dark fill tokens right after the toggle",
      })
      .toEqual(fills);
    expect(await rowFills(page), "every row shares the fill of its segment").toEqual(fills);
  });

  test("design: a click on a row still cycles its color", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await open(page);
    await add(page, NAMES.slice(0, 2));
    const row = page.locator(ROW).first();
    const before = await row.evaluate((element) => element.style.backgroundColor);
    expect(before, "the app keeps its own row color inline").not.toBe("");
    await row.click({ position: { x: 20, y: 10 } });
    await expect
      .poll(() => row.evaluate((element) => element.style.backgroundColor), {
        message: "the row takes the next color after a click",
      })
      .not.toBe(before);
  });

  test("design: the buttons turn busy while the wheel spins and return to the palette after it", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.clock.install();
    await open(page);
    await add(page, NAMES.slice(0, 4));
    await page.addStyleTag({ content: FREEZE });
    await page.locator(CANVAS).click();
    for (const selector of [ADD, REMOVE_ALL]) {
      await expect(page.locator(selector), `${selector} carries the busy marker while spinning`).toHaveAttribute(
        "data-design-busy",
        "true",
      );
      await assertToken(page, selector, "background-color", "--design-surface-3", `${selector} busy`);
      await assertToken(page, selector, "color", "--design-text-muted", `${selector} busy text`);
    }
    await page.clock.runFor(20_000);
    await expect(page.locator(WINNER)).toHaveText(/^Winner: /, { timeout: resolveTimeout(10_000) });
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      for (const selector of [ADD, REMOVE_ALL]) {
        await expect(page.locator(selector), `${selector} drops the busy marker after the spin`).not.toHaveAttribute(
          "data-design-busy",
          "true",
        );
        await assertToken(page, selector, "background-color", "--design-primary", `${selector} after spin ${mode}`);
      }
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [WINNER], "roulette wheel winner");
  });

  test("design: the native toggle mirrors into data-design-theme and leaves no inline colors", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await open(page);
      await expect(page.locator(TOGGLE_ICON), `icon follows ${mode}`).toHaveAttribute(
        "src",
        mode === "light" ? "static/sun.png" : "static/moon.png",
      );
      await toggleTheme(page);
      const flipped = mode === "light" ? "dark" : "light";
      await expect(page.locator("html")).toHaveAttribute("data-design-theme", flipped);
      await expect(page.locator(TOGGLE_ICON)).toHaveAttribute(
        "src",
        flipped === "light" ? "static/sun.png" : "static/moon.png",
      );
      expect(
        await page.locator("body").evaluate((body) => body.style.backgroundColor + body.style.color),
        "the toggle leaves no inline body colors",
      ).toBe("");
      await page.addStyleTag({ content: FREEZE });
      await assertToken(page, "body", "background-color", "--design-surface-1", `page after toggle from ${mode}`);
      await toggleTheme(page);
      await expect(page.locator("html"), `a second click returns to ${mode}`).toHaveAttribute("data-design-theme", mode);
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: the delete icon takes the text color of its row", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await open(page);
    await add(page, NAMES.slice(0, 6));
    await page.addStyleTag({ content: FREEZE });
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      const icons = await page.locator(`${ROW} .item-delete`).evaluateAll((elements) =>
        elements.map((icon) => {
          const style = getComputedStyle(icon);
          return {
            row: icon.parentElement.textContent.trim(),
            fill: style.backgroundColor,
            text: getComputedStyle(icon.parentElement).color,
            mask: style.maskImage || style.webkitMaskImage || "",
          };
        }),
      );
      expect(icons, "every row carries a delete icon").toHaveLength(6);
      for (const icon of icons) {
        expect(icon.fill, `the delete icon of '${icon.row}' paints the row's text color in ${mode} mode`).toBe(icon.text);
        expect(icon.mask, `the delete icon of '${icon.row}' keeps the app's icon shape`).toContain("/static/close.png");
      }
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: every image the role stylesheet references is served", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await open(page);
    const sheet = await page
      .locator("link[href*='/roles/web-app-roulette-wheel/'][href*='style.css']")
      .first()
      .getAttribute("href");
    const css = await (await apiGetOnion(page.request, sheet)).text();
    const targets = [...new Set([...css.matchAll(/url\(\s*["']?([^"')]+)["']?\s*\)/g)].map((match) => match[1]))]
      .filter((target) => !target.startsWith("data:"))
      .map((target) => new URL(target, sheet).href);
    expect(targets.length, "the role stylesheet references images").toBeGreaterThan(0);
    for (const target of targets) {
      const served = await apiGetOnion(page.request, target);
      expect(
        `${served.status()} ${served.headers()["content-type"]}`,
        `${target} must be served as an image; a relative url() resolves against the stylesheet on the CDN`,
      ).toMatch(/^200 image\//);
    }
  });

  test("design: a keyboard focus stop draws its indicator in the link tone", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await open(page);
    await add(page, NAMES.slice(0, 2));
    const expected = await tokenValue(page, "--design-link", "color");
    for (const selector of [INPUT, ADD, REMOVE_ALL]) {
      const control = page.locator(selector);
      await focusByKeyboard(page, control);
      const outline = await control.evaluate((element) => {
        const style = getComputedStyle(element);
        return { color: style.outlineColor, style: style.outlineStyle, width: parseFloat(style.outlineWidth) };
      });
      expect(outline.style, `a focused '${selector}' must draw an outline`).not.toBe("none");
      expect(outline.width, `a focused '${selector}' must draw an outline`).toBeGreaterThan(0);
      expect(outline.color, `the outline of '${selector}' takes --design-link`).toBe(expected);
    }
  });

  test("design: the page carries the configured favicon and title", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!faviconUrl && !title, "logo and title replacement are disabled for this role");
    await open(page);
    if (title) {
      await expect.poll(() => page.title(), { message: "the page carries the configured title" }).toBe(title);
    }
    if (faviconUrl) {
      await expect(page.locator("link[rel~='icon']")).toHaveCount(1);
      await expect(page.locator("link[rel~='icon']")).toHaveAttribute("href", faviconUrl);
      const served = await apiGetOnion(page.request, faviconUrl);
      expect(served.status(), "the favicon must be served").toBe(200);
      expect(served.headers()["content-type"] || "", "the favicon is a PNG").toContain("image/png");
    }
  });

  function galleryViews() {
    const view = (name, prepare, extra = {}) => ({ name, url: `${base}/`, prepare, ...extra });
    const seeded = (name, count, then, extra) =>
      view(
        name,
        async (page) => {
          await ready(page);
          await add(page, NAMES.slice(0, count));
          if (then) await then(page);
        },
        extra,
      );
    const winner = (name, count, then, extra) =>
      seeded(
        name,
        count,
        async (page) => {
          await spin(page);
          if (then) await then(page);
        },
        extra,
      );
    const credits = async (page) => {
      await page.locator("footer p").click();
      await expect(page.locator(CREDITS)).toBeVisible({ timeout: resolveTimeout(10_000) });
    };
    return [
      view("wheel-empty", ready),
      view("input-focus", async (page) => {
        await ready(page);
        await focusByKeyboard(page, page.locator(INPUT));
      }),
      view("input-filled", async (page) => {
        await ready(page);
        await page.locator(INPUT).fill(NAMES[0]);
      }),
      seeded("one-item", 1),
      seeded("few-items", 4),
      view("long-names", async (page) => {
        await ready(page);
        await add(page, LONG_NAMES);
      }),
      seeded("full-list", 16),
      seeded("full-list-wheel", 16, (page) =>
        page.locator(CANVAS).evaluate((canvas) => canvas.scrollIntoView({ behavior: "instant", block: "center" })),
      ),
      seeded("add-hover", 3, (page) => page.locator(ADD).hover()),
      seeded("add-focus", 3, (page) => focusByKeyboard(page, page.locator(ADD))),
      seeded("remove-all-hover", 3, (page) => page.locator(REMOVE_ALL).hover()),
      seeded("remove-all-focus", 3, (page) => focusByKeyboard(page, page.locator(REMOVE_ALL))),
      seeded("item-recolored", 3, (page) => page.locator(ROW).nth(1).click({ position: { x: 20, y: 10 } })),
      winner("winner", 6),
      winner("winner-full-list", 16),
      seeded("credits-open", 3, credits),
      seeded("credits-link-hover", 3, async (page) => {
        await credits(page);
        await page.locator(`${CREDITS} a`).first().hover();
      }),
      seeded("credits-link-focus", 3, async (page) => {
        await credits(page);
        await focusByKeyboard(page, page.locator(`${CREDITS} a`).first());
      }),
      seeded("theme-toggled", 4, toggleTheme, { afterOnly: true }),
      winner("theme-toggled-winner", 6, toggleTheme, { afterOnly: true }),
    ];
  }

  test("design: gallery of the wheel states", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(1_200_000));
    await page.clock.install();
    await captureDesignGallery(page, galleryViews());
  });
};
