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
const { apiGetOnion, decodeDotenvQuotedValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const MODES = ["light", "dark"];
const SHELL = "#root > [data-layout-variant]";
const SAVE = "button:text-is('Save')";
const DIVIDER = "main [class~='border-border']";
const SIDEBAR_LOGO = "#app-sidebar > div:first-child > div:first-child > span:last-child";
const CORPORATE_THEME = /Corporate design/;
const CORPORATE_THEME_NAME = "corporate";
const TERMINAL_PAINTED_BYTES = 8_000;
const TERMINAL_STARTUP_MS = 15_000;
const SHOWCASE_JOB = "Design showcase";
const SHOWCASE_SESSION = "Corporate design review";
const SHOWCASE_SESSIONS = [
  {
    id: "design-showcase-review",
    source: "cli",
    title: SHOWCASE_SESSION,
    model: "showcase/model",
    started_at: 1767258000,
    ended_at: 1767259800,
    messages: [
      { role: "user", content: "Which views does the corporate design review cover?" },
      {
        role: "assistant",
        content:
          "The review covers three areas:\n\n1. **Light mode** on desktop and mobile\n2. **Dark mode** on desktop and mobile\n3. Hover, focus and selected states\n\nRun `make design-gallery` to capture them.",
      },
      { role: "user", content: "Thanks, please keep the checklist short." },
      { role: "assistant", content: "Done. The checklist has three entries." },
    ],
  },
  {
    id: "design-showcase-status",
    source: "telegram",
    title: "Weekly status summary",
    model: "showcase/model",
    started_at: 1767171600,
    ended_at: 1767172500,
    messages: [
      { role: "user", content: "Summarize this week." },
      { role: "assistant", content: "Four deployments, no incidents, two open reviews." },
    ],
  },
  {
    id: "design-showcase-deploy",
    source: "cron",
    title: "Deploy checklist",
    model: "showcase/model",
    started_at: 1767085200,
    ended_at: 1767085800,
    messages: [
      { role: "user", content: "List the deploy checklist." },
      { role: "assistant", content: "- Gate green\n- Deploy green\n- Gallery reviewed" },
    ],
  },
];

async function seedShowcase(page, base) {
  const imported = await page.request.post(`${base}/api/sessions/import`, { data: { sessions: SHOWCASE_SESSIONS } });
  expect(imported.ok(), "seeding the showcase sessions").toBe(true);
  const jobs = await (await page.request.get(`${base}/api/cron/jobs`)).json();
  if (!jobs.some((job) => job.name === SHOWCASE_JOB)) {
    const created = await page.request.post(`${base}/api/cron/jobs`, {
      data: {
        name: SHOWCASE_JOB,
        prompt: "Summarize the open design reviews.",
        schedule: "0 9 * * 1",
        deliver: "local",
        paused: true,
      },
    });
    expect(created.ok(), "seeding the showcase cron job").toBe(true);
  }
}

async function ready(page) {
  await page.waitForLoadState("networkidle");
}

async function openNavigation(page) {
  await ready(page);
  const toggle = page.getByRole("button", { name: "Open navigation" });
  if (await toggle.isVisible()) await toggle.click();
}

async function openHistory(page) {
  await ready(page);
  await page.getByRole("radio", { name: "History" }).click();
}

function dialog(trigger) {
  return async (page) => {
    await ready(page);
    await page.getByRole("button", { name: trigger, exact: true }).first().click();
    await expect(page.getByRole("dialog")).toBeVisible();
  };
}

function listbox(trigger, title) {
  return async (page) => {
    await openNavigation(page);
    await page.getByRole("button", { name: trigger }).click();
    await expect(page.getByRole("listbox", { name: title }).getByRole("option").first()).toBeInViewport({ ratio: 1 });
  };
}

/**
 * Args:
 *   page: Playwright page whose chat terminal is watched.
 *
 * Returns:
 *   An object whose `prompt` flag turns true once the terminal stream of the current document carried the prompt.
 */
function watchTerminal(page) {
  const terminal = { prompt: false };
  page.on("framenavigated", (frame) => {
    if (frame === page.mainFrame()) terminal.prompt = false;
  });
  page.on("websocket", (socket) => {
    socket.on("framereceived", ({ payload }) => {
      if (payload.toString().includes("❯")) terminal.prompt = true;
    });
  });
  return terminal;
}

/**
 * Args:
 *   page: Playwright page that shows the chat view.
 *   terminal: the watcher returned by `watchTerminal` for that page.
 */
async function terminalPainted(page, terminal) {
  await expect
    .poll(() => terminal.prompt, {
      message: "the chat terminal stream must carry the prompt",
      timeout: resolveTimeout(60_000),
    })
    .toBe(true);
  await expect
    .poll(async () => (await page.locator(".xterm").screenshot()).length, {
      message: "the chat terminal must have painted its content",
    })
    .toBeGreaterThan(TERMINAL_PAINTED_BYTES);
}

async function chooseTheme(page, name) {
  await page.getByRole("button", { name: "Switch theme" }).click();
  await page.getByRole("option", { name }).click();
}

/**
 * Args:
 *   page: signed-in dashboard page whose theme switcher was just used.
 *   baseUrl: dashboard origin.
 *   name: theme name the gateway must report before the context may close.
 */
async function awaitPersistedTheme(page, baseUrl, name) {
  await expect
    .poll(
      async () => {
        const response = await apiGetOnion(page.request, `${baseUrl}/api/config?profile=default`);
        return response.ok() ? (await response.json()).dashboard.theme : response.status();
      },
      {
        message: "the gateway must persist the theme; every later browser context reads it from config.yaml",
        timeout: resolveTimeout(60_000),
      },
    )
    .toBe(name);
}

/**
 * Args:
 *   page: signed-in dashboard page that loads the kanban plugin stylesheet.
 *
 * Returns:
 *   Per severity, the marker border and the label color of a kanban diagnostic card.
 */
async function kanbanDiagnostics(page) {
  return page.evaluate(() => {
    const result = {};
    for (const severity of ["warning", "error", "critical"]) {
      const card = document.createElement("div");
      card.className = `hermes-kanban-diag hermes-kanban-diag--${severity}`;
      const label = document.createElement("span");
      label.className = "hermes-kanban-diag-sev";
      label.textContent = severity;
      card.appendChild(label);
      document.querySelector("#root").appendChild(card);
      result[severity] = [getComputedStyle(card).borderLeftColor, getComputedStyle(label).color];
      card.remove();
    }
    return result;
  });
}

exports.register = function (shared) {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("webui");
    skipUnlessServiceEnabled("design");
    await shared.openSignIn(page);
    await assertDesignTokens(page, "hermes");
  });

  test("design: sign-in page, primary action and text take the palette", async ({ page }) => {
    skipUnlessServiceEnabled("webui");
    skipUnlessServiceEnabled("design");
    await shared.openSignIn(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "body", "background-color", "--design-surface-1", `sign-in ${mode}`);
      await assertToken(page, "h1", "color", "--design-text", `sign-in ${mode}`);
      await assertToken(page, ".provider-btn", "background-color", "--design-primary", `sign-in ${mode}`);
      await assertToken(page, ".provider-btn", "color", "--design-on-primary", `sign-in ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, ".card", "hermes sign-in");
    await assertReadable(
      page,
      [
        "h1",
        ".subtitle",
        ".provider-btn",
        "footer",
        { selector: ".form-title", optional: true },
        { selector: ".field-label", optional: true },
      ],
      "hermes sign-in",
    );
  });

  test("design: dashboard shell, primary action and text take the palette", async ({ page }) => {
    skipUnlessServiceEnabled("webui");
    skipUnlessServiceEnabled("design");
    await shared.signIn(page, "/config");
    await expect(page.locator(SAVE).first()).toBeVisible();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.style.getPropertyValue("--midground-base")), {
        message: "the dashboard must take its text color from the corporate theme",
      })
      .toBe("var(--design-text)");
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, SHELL, "background-color", "--design-surface-1", `dashboard ${mode}`);
      await assertToken(page, SAVE, "background-color", "--design-primary", `dashboard ${mode}`);
      await assertToken(page, SAVE, "color", "--design-on-primary", `dashboard ${mode}`);
      await assertToken(page, DIVIDER, "border-top-color", "--design-border", `dashboard card border ${mode}`);
      expect(await tokenValue(page, "--color-border", "border-top-color"), `plugin border variable ${mode}`).toBe(
        await tokenValue(page, "--design-border", "border-top-color"),
      );
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, SHELL, "hermes dashboard");
    await assertReadable(
      page,
      [
        "#app-sidebar nav a[aria-current='page']",
        "#app-sidebar nav a:not([aria-current])",
        "header[role='banner'] h1",
        "main h3",
        "main label",
        "main input:not([type='file'])",
        "main [class~='text-text-secondary']",
      ],
      "hermes dashboard",
    );
  });

  test("design: kanban diagnostics take the status tokens", async ({ page }) => {
    skipUnlessServiceEnabled("webui");
    skipUnlessServiceEnabled("design");
    await shared.signIn(page, "/kanban");
    await ready(page);
    for (const mode of MODES) {
      await page.emulateMedia({ colorScheme: mode });
      const warning = await tokenValue(page, "--design-warning", "color");
      const danger = await tokenValue(page, "--design-danger", "color");
      expect(await kanbanDiagnostics(page), `kanban diagnostics ${mode}`).toEqual({
        warning: [warning, warning],
        error: [danger, danger],
        critical: [danger, danger],
      });
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: a theme chosen in the dashboard replaces the corporate one and sets the mode", async ({ page }) => {
    skipUnlessServiceEnabled("webui");
    skipUnlessServiceEnabled("design");
    await shared.signIn(page, "/sessions");
    await page.emulateMedia({ colorScheme: "light" });
    const html = page.locator("html");
    await assertToken(page, SHELL, "background-color", "--design-surface-1", "corporate theme");
    await expect(html, "the corporate theme follows the browser preference").not.toHaveAttribute("data-design-theme");
    const lightSurface = await tokenValue(page, "--design-surface-1", "background-color");

    await chooseTheme(page, "Midnight");
    await expect(html).toHaveAttribute("data-design-theme", "dark");
    const darkSurface = await tokenValue(page, "--design-surface-1", "background-color");
    expect(darkSurface, "a dark dashboard theme must switch the tokens while the browser prefers light").not.toBe(
      lightSurface,
    );
    await expect(page.locator(SHELL), "a chosen theme must keep its own palette").not.toHaveCSS(
      "background-color",
      darkSurface,
    );

    await chooseTheme(page, CORPORATE_THEME);
    await expect(html).not.toHaveAttribute("data-design-theme");
    await assertToken(page, SHELL, "background-color", "--design-surface-1", "corporate theme chosen again");
    await awaitPersistedTheme(page, shared.env.baseUrl, CORPORATE_THEME_NAME);
  });

  test("design: the dashboard shows the generated logo and the configured title", async ({ page }) => {
    skipUnlessServiceEnabled("webui");
    skipUnlessServiceEnabled("design");
    const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL);
    const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE);
    test.skip(!logoUrl && !title, "logo and title replacement are disabled for this role");

    await shared.openSignIn(page);
    if (title) await expect(page).toHaveTitle(title);
    if (logoUrl) {
      expect((await apiGetOnion(page.request, logoUrl)).ok(), "the generated logo is published on the CDN").toBe(true);
      await expect(page.locator(".brand")).toHaveCSS("background-image", `url("${logoUrl}")`);
    }

    await shared.signIn(page);
    if (title) await expect(page).toHaveTitle(title);
    if (logoUrl) {
      const logo = page.locator(SIDEBAR_LOGO);
      await expect(logo).toHaveCSS("background-image", `url("${logoUrl}")`);
      const box = await logo.boundingBox();
      expect(box, "the sidebar logo must render").not.toBeNull();
      expect(box.width, "the sidebar logo box must be wider than high for the wordmark lockup").toBeGreaterThan(
        box.height * 1.5,
      );
      const favicon = await page.locator("link[rel='icon']").getAttribute("href");
      expect((await apiGetOnion(page.request, favicon)).ok(), "the generated favicon is published on the CDN").toBe(true);
    }
  });

  test("design: gallery of sign-in, agent and administration views", async ({ page }) => {
    skipUnlessServiceEnabled("webui");
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(1_800_000));
    const base = shared.env.baseUrl;
    const failures = [];
    const capture = async (views) => {
      try {
        await captureDesignGallery(page, views);
      } catch (error) {
        failures.push(error.message);
      }
    };

    await shared.openSignIn(page);
    await capture([
      { name: "login", url: `${base}/login` },
      {
        name: "login-focus",
        url: `${base}/login`,
        prepare: (current) => current.locator(".provider-list :is(input.field-input, a.provider-btn)").first().focus(),
      },
    ]);

    const terminal = watchTerminal(page);
    await shared.signIn(page, "/chat");
    await seedShowcase(page, base);
    await terminalPainted(page, terminal);
    await page.waitForTimeout(resolveTimeout(TERMINAL_STARTUP_MS));

    await capture([
      { name: "sessions", url: `${base}/sessions`, prepare: ready },
      {
        name: "session-open",
        url: `${base}/sessions`,
        prepare: async (current) => {
          await openHistory(current);
          await current.getByText(SHOWCASE_SESSION, { exact: true }).click();
          await expect(current.getByText("Done. The checklist has three entries.")).toBeVisible();
        },
      },
      {
        name: "session-selected",
        url: `${base}/sessions`,
        prepare: async (current) => {
          await openHistory(current);
          await current.getByRole("checkbox", { name: "Select session" }).first().click();
        },
      },
      {
        name: "chat",
        url: `${base}/chat`,
        prepare: (current) => terminalPainted(current, terminal),
      },
      { name: "files", url: `${base}/files`, prepare: ready },
      { name: "models", url: `${base}/models`, prepare: ready },
      { name: "logs", url: `${base}/logs`, prepare: ready },
      { name: "cron", url: `${base}/cron`, prepare: ready },
      { name: "cron-create", url: `${base}/cron`, prepare: dialog("Create") },
      { name: "skills", url: `${base}/skills`, prepare: ready },
      { name: "kanban", url: `${base}/kanban`, prepare: ready },
      {
        name: "plugins",
        url: `${base}/plugins`,
        prepare: async (current) => {
          await ready(current);
          await expect(current.locator("[data-testid='plugin-catalog-section']")).toBeVisible();
        },
      },
      { name: "mcp", url: `${base}/mcp`, prepare: ready },
      { name: "mcp-add", url: `${base}/mcp`, prepare: dialog("Add Server") },
      { name: "channels", url: `${base}/channels`, prepare: ready },
      { name: "webhooks", url: `${base}/webhooks`, prepare: ready },
      { name: "pairing", url: `${base}/pairing`, prepare: ready },
      { name: "profiles", url: `${base}/profiles`, prepare: ready },
      { name: "profile-new", url: `${base}/profiles/new`, prepare: ready },
      { name: "config", url: `${base}/config`, prepare: ready },
      { name: "keys", url: `${base}/env`, prepare: ready },
      { name: "system", url: `${base}/system`, prepare: ready },
      { name: "achievements", url: `${base}/achievements`, prepare: ready },
      { name: "theme-switcher", url: `${base}/sessions`, prepare: listbox("Switch theme", "Theme") },
      { name: "language-switcher", url: `${base}/sessions`, prepare: listbox("Switch language", "Switch language") },
      {
        name: "navigation",
        url: `${base}/sessions`,
        prepare: async (current) => {
          await openNavigation(current);
          await current.locator("#app-sidebar a[href$='/cron']").hover();
        },
      },
    ]);
    expect(failures, failures.join("\n")).toEqual([]);
  });
};
