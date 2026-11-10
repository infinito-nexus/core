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
const { apiFetchOnion, apiGetOnion, decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const base = normalizeBaseUrl(process.env.APP_BASE_URL);
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const SHOWCASE = "Sandbox/DesignShowcase";
const SHOWCASE_REST = `${base}/rest/wikis/xwiki/spaces/Sandbox/pages/DesignShowcase`;
const ADMIN = "/bin/admin/XWiki/XWikiPreferences?editor=globaladmin&section=";
const SEARCH = "/bin/view/Main/Search?f_type=DOCUMENT&f_locale=en&f_locale=&r=1&text=";
const INJECTED_SNIPPETS = /<!--infinito-inj-->[\s\S]*?<!--\/infinito-inj-->/g;
const NAVBAR = ".navbar";

function adminAuth() {
  return `Basic ${Buffer.from(`${adminUsername}:${adminPassword}`).toString("base64")}`;
}

async function open(page, path, selector) {
  await gotoOnion(page, `${base}${path}`);
  await expect(page.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(120_000) });
}

async function openHome(page) {
  await open(page, "/bin/view/Main/", "#xwikicontent");
}

async function signIn(page) {
  test.skip(
    process.env.SSO_SERVICE_ENABLED === "true" || process.env.LDAP_SERVICE_ENABLED === "true",
    "the local administrator exists only without SSO and LDAP",
  );
  await open(page, "/bin/login/XWiki/XWikiLogin", "#j_password");
  await page.locator("#j_username").fill(adminUsername);
  await page.locator("#j_password").fill(adminPassword);
  await page.locator("#loginForm input[type='submit']").click();
  await expect(page.locator("html[data-xwiki-user-reference]")).toHaveCount(1, { timeout: resolveTimeout(120_000) });
}

async function seedShowcase(request) {
  const headers = { Authorization: adminAuth(), "Content-Type": "application/xml", Accept: "application/json" };
  const page = (text) =>
    `<page xmlns="http://www.xwiki.org"><title>Design Showcase</title><syntax>xwiki/2.1</syntax><content><![CDATA[${text}]]></content></page>`;
  const first = "== Showcase ==\n\nA paragraph with a [[link to the home page>>Main.WebHome]].";
  const second = [
    first,
    "{{info}}An information box.{{/info}}",
    "{{success}}A success box.{{/success}}",
    "{{warning}}A warning box.{{/warning}}",
    "{{error}}An error box.{{/error}}",
    "|=Name|=Value\n|One|1\n|Two|2\n|Three|3",
    '{{code language="js"}}const answer = 42;{{/code}}',
    "----",
    "* first item\n* second item",
  ].join("\n\n");
  const existing = await apiGetOnion(request, SHOWCASE_REST, { headers });
  if (existing.status() === 404) {
    for (const text of [first, second]) {
      const saved = await apiFetchOnion(request, SHOWCASE_REST, { method: "PUT", headers, data: page(text) });
      expect(saved.ok(), `showcase page save answers ${saved.status()}`).toBe(true);
    }
  }
  const attachments = await (await apiGetOnion(request, `${SHOWCASE_REST}/attachments`, { headers })).json();
  if (attachments.attachments.length === 0) {
    const attached = await apiFetchOnion(request, `${SHOWCASE_REST}/attachments/showcase.txt`, {
      method: "PUT",
      headers: { Authorization: adminAuth(), "Content-Type": "text/plain" },
      data: "A showcase attachment.",
    });
    expect(attached.ok(), `showcase attachment answers ${attached.status()}`).toBe(true);
  }
  const comments = await (await apiGetOnion(request, `${SHOWCASE_REST}/comments`, { headers })).json();
  if (comments.comments.length === 0) {
    const commented = await apiFetchOnion(request, `${SHOWCASE_REST}/comments`, {
      method: "POST",
      headers,
      data: '<comment xmlns="http://www.xwiki.org"><text>A showcase comment.</text></comment>',
    });
    expect(commented.ok(), `showcase comment answers ${commented.status()}`).toBe(true);
  }
}

async function waitForPanel(panel) {
  await expect(panel).toBeVisible({ timeout: resolveTimeout(15_000) });
  await expect
    .poll(
      () =>
        panel.evaluate(
          (el) =>
            el.getAnimations({ subtree: true }).filter((animation) => animation.playState === "running").length === 0 &&
            getComputedStyle(el).opacity === "1",
        ),
      { timeout: resolveTimeout(15_000) },
    )
    .toBe(true);
}

async function dismissTour(page) {
  const close = page.locator(".popover.tour a.btn-default").first();
  await close
    .waitFor({ state: "visible", timeout: resolveTimeout(5_000) })
    .then(() => close.click())
    .catch(() => {});
  await expect(page.locator(".popover.tour")).toHaveCount(0);
}

async function stripInjected(route) {
  if (route.request().resourceType() !== "document") return route.continue();
  const response = await route.fetch();
  return route.fulfill({ response, body: (await response.text()).replace(INJECTED_SNIPPETS, "") });
}

function hex(rgb) {
  return `#${rgb.match(/\d+/g).slice(0, 3).map((channel) => Number(channel).toString(16).padStart(2, "0")).join("")}`;
}

async function currentThemePath(page) {
  const href = await page.locator("link[href*='/skins/flamingo/style']").first().getAttribute("href");
  return new URL(href, base).searchParams.get("colorTheme").replace(/^xwiki:/, "").replace(".", "/");
}

exports.register = function () {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openHome(page);
    await assertDesignTokens(page, "xwiki");
  });

  test("design: page, navbar, text and links take the palette", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openHome(page);
    for (const colorScheme of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme });
      await assertToken(page, "body", "background-color", "--design-surface-1", `xwiki page ${colorScheme}`);
      await assertToken(page, "#mainContentArea", "background-color", "--design-surface-2", `xwiki content ${colorScheme}`);
      await assertToken(page, "#xwikicontent", "color", "--design-text", `xwiki body text ${colorScheme}`);
      await assertToken(page, "#xwikicontent a", "color", "--design-link", `xwiki link ${colorScheme}`);
      await assertToken(page, NAVBAR, "background-color", "--design-frame", `xwiki navbar ${colorScheme}`);
      await assertToken(page, "#tmDrawerActivator", "color", "--design-on-frame", `xwiki navbar text ${colorScheme}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, "#xwikicontent", "xwiki");
    await assertReadable(page, ["#xwikicontent", "#xwikicontent a", "#tmDrawerActivator"], "xwiki");
  });

  test("design: every image the role stylesheet references is served", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openHome(page);
    const sheet = await page.locator("link[href*='/roles/web-app-xwiki/'][href*='style.css']").first().getAttribute("href");
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

  test("design: the color theme carries the light palette without the role stylesheet", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await page.emulateMedia({ colorScheme: "light" });
    await openHome(page);
    const expected = {
      frame: await tokenValue(page, "--design-frame", "background-color"),
      surface: await tokenValue(page, "--design-surface-1", "background-color"),
      text: await tokenValue(page, "--design-text", "color"),
    };
    await page.route("**/*", stripInjected);
    await openHome(page);
    await expect(page.locator("link[href*='_shared/css/default.css']"), "the injected sheets are stripped").toHaveCount(0);
    expect(await currentThemePath(page), "the skin sheet is compiled for the corporate theme").toBe(
      decodeDotenvQuotedValue(process.env.DESIGN_THEME_REFERENCE).replace(".", "/"),
    );
    const style = (selector, property) =>
      page.locator(selector).first().evaluate((el, prop) => getComputedStyle(el).getPropertyValue(prop), property);
    expect(await style(NAVBAR, "background-color"), "the theme paints the navbar in the frame color").toBe(expected.frame);
    expect(await style("body", "background-color"), "the theme paints the page in surface-1").toBe(expected.surface);
    expect(await style("#xwikicontent", "color"), "the theme sets the body text color").toBe(expected.text);
  });

  test("design: primary action reads on-primary, fields and dividers read the border tokens", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await open(page, `${SEARCH}xwiki`, ".search-results");
    for (const colorScheme of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme });
      await assertToken(page, ".btn-primary", "background-color", "--design-primary", `xwiki primary ${colorScheme}`);
      await assertToken(page, ".btn-primary", "color", "--design-on-primary", `xwiki on-primary ${colorScheme}`);
      await assertToken(page, "input.form-control", "border-top-color", "--design-border-strong", `xwiki field ${colorScheme}`);
    }
    await open(page, "/bin/view/Main/", ".xwikitabbar");
    for (const colorScheme of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme });
      await assertToken(page, ".xwikitabbar", "border-bottom-color", "--design-border", `xwiki tab divider ${colorScheme}`);
    }
  });

  test("design: search facets take their surface and text from the tokens", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await open(page, `${SEARCH}xwiki`, ".search-facet-header label");
    for (const colorScheme of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme });
      await assertToken(page, ".search-facet-header", "background-color", "--design-surface-3", `xwiki facet header ${colorScheme}`);
      await assertToken(page, ".search-facet-header label", "color", "--design-text", `xwiki facet label ${colorScheme}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertReadable(page, [".search-facet-header label"], "xwiki search facets");
  });

  test("design: focus stops inside the navbar draw in the frame text color", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await open(page, `${SEARCH}xwiki`, ".search-results");
    const onFrame = await tokenValue(page, "--design-on-frame", "outline-color");
    let stops = 0;
    for (let step = 0; step < 25; step += 1) {
      await page.keyboard.press("Tab");
      const outline = await page.evaluate((navbar) => {
        const el = document.activeElement;
        if (!el || !el.closest(navbar)) return null;
        const style = getComputedStyle(el);
        return { color: style.outlineColor, style: style.outlineStyle };
      }, NAVBAR);
      if (!outline) continue;
      stops += 1;
      expect(outline.style, "a focus stop inside the navbar draws an outline").not.toBe("none");
      expect(outline.color, "focus outline inside the navbar").toBe(onFrame);
    }
    expect(stops, "the Tab walk reaches the navbar").toBeGreaterThan(0);
  });

  test("design: logo and title are the configured ones", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await openHome(page);
    const title = decodeDotenvQuotedValue(process.env.DESIGN_TITLE);
    if (title) {
      expect((await page.title()).endsWith(` - ${title}`), `the page title '${await page.title()}' ends with the design title`).toBe(true);
    }
    const logoUrl = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL);
    test.skip(!logoUrl, "the logo replacement is disabled");
    const logo = page.locator("#companylogo img");
    await expect(logo).toBeVisible();
    const box = await logo.boundingBox();
    expect(box.width, "the navbar logo is a lockup, wider than high").toBeGreaterThan(box.height * 1.5);
    const src = await logo.evaluate((img) => img.src);
    expect(decodeURIComponent(src), "the logo is the attachment of the corporate theme page").toContain(
      `/${decodeDotenvQuotedValue(process.env.DESIGN_THEME_REFERENCE).replace(".", "/")}/`,
    );
    const served = await apiGetOnion(page.request, src);
    const generated = await apiGetOnion(page.request, logoUrl);
    expect(generated.ok(), `the generated logo answers ${generated.status()}`).toBe(true);
    expect(Buffer.compare(await served.body(), await generated.body()), "XWiki serves the generated lockup").toBe(0);
    const onFrame = hex(await tokenValue(page, "--design-on-frame", "color"));
    expect((await generated.text()).toLowerCase(), "the lockup text uses the frame text color").toContain(`fill="${onFrame}"`);
  });

  test("design: the administrator signs in through the form and administers the wiki", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signIn(page);
    await expect(page.locator("html")).toHaveAttribute("data-xwiki-user-reference", `xwiki:XWiki.${adminUsername}`);
    await open(page, `${ADMIN}Themes`, "#admin-page-content form");
    await expect(page.locator("#admin-page-content select[name$='_colorTheme']")).toHaveValue(
      decodeDotenvQuotedValue(process.env.DESIGN_THEME_REFERENCE),
    );
    await assertReadable(page, ["#admin-page-content dt label", "#admin-page-content .xHint"], "xwiki administration form");
    await seedShowcase(page.request);
    await open(page, `/bin/view/${SHOWCASE}?viewer=history`, "#historycontent table td");
    for (const colorScheme of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme });
      await assertToken(page, "#historycontent table td", "border-top-color", "--design-border", `xwiki divider ${colorScheme}`);
    }
  });

  test("design: gallery of wiki and administration views", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(2_400_000));
    const view = (name, path, selector, prepare) => ({
      name,
      url: `${base}${path}`,
      prepare: async (p) => {
        await expect(p.locator(selector).first()).toBeVisible({ timeout: resolveTimeout(120_000) });
        if (prepare) await prepare(p);
      },
    });
    const failures = [];
    await captureDesignGallery(page, [
      view("home", "/bin/view/Main/", "#xwikicontent", dismissTour),
      view("sign-in", "/bin/login/XWiki/XWikiLogin", "#loginForm #j_password"),
    ]).catch((error) => failures.push(error.message));
    await signIn(page);
    await seedShowcase(page.request);
    const theme = await currentThemePath(page);
    await captureDesignGallery(page, [
      view("page-view", `/bin/view/${SHOWCASE}`, "#xwikicontent h2"),
      view("page-edit-wiki", `/bin/edit/${SHOWCASE}?editor=wiki`, ".buttons"),
      view("page-edit-wysiwyg", `/bin/edit/${SHOWCASE}?editor=wysiwyg`, ".cke_top"),
      view("page-history", `/bin/view/${SHOWCASE}?viewer=history`, "#historycontent table"),
      view("page-diff", `/bin/view/${SHOWCASE}?viewer=changes&rev1=1.1&rev2=2.1`, "#changescontent"),
      view("page-comments", `/bin/view/${SHOWCASE}?viewer=comments`, ".xwikicomment"),
      view("page-attachments", `/bin/view/${SHOWCASE}?viewer=attachments`, "#attachmentscontent"),
      view("page-rights", `/bin/edit/${SHOWCASE}?editor=rights`, '#usersandgroupstable :text("XWikiAllGroup")'),
      view("actions-menu-open", `/bin/view/${SHOWCASE}`, "#tmMoreActions .dropdown-toggle", async (p) => {
        await p.locator("#tmMoreActions .dropdown-toggle").click();
        await waitForPanel(p.locator("#tmMoreActions .dropdown-menu"));
      }),
      view("drawer-open", `/bin/view/${SHOWCASE}`, "#tmDrawerActivator", async (p) => {
        await p.locator("#tmDrawerActivator").click();
        await waitForPanel(p.locator("#tmDrawer"));
      }),
      view("search", `${SEARCH}showcase`, ".search-results"),
      view("page-index", "/bin/view/Main/AllDocs", ".liveData table tbody tr"),
      view("user-profile", `/bin/view/XWiki/${adminUsername}`, ".userInfo"),
      view("user-preferences", `/bin/view/XWiki/${adminUsername}?category=preferences`, "#preferencesPane"),
      view("admin-home", "/bin/admin/XWiki/XWikiPreferences", ".admin-menu"),
      view("admin-themes", `${ADMIN}Themes`, "#admin-page-content form"),
      view("admin-presentation", `${ADMIN}Presentation`, "#admin-page-content form"),
      view("admin-users", `${ADMIN}Users`, "#admin-page-content table tbody tr"),
      view("admin-groups", `${ADMIN}Groups`, "#admin-page-content table tbody tr"),
      view("admin-rights", `${ADMIN}Rights`, '#usersandgroupstable :text("XWikiAllGroup")'),
      view("admin-extensions", `${ADMIN}XWiki.Extensions`, "#admin-page-content form"),
      view("theme-editor", `/bin/edit/${theme}?editor=inline`, "#inline"),
      view("not-found", "/bin/view/Sandbox/DesignShowcaseMissing", ".xwikimessage"),
    ]).catch((error) => failures.push(error.message));
    expect(failures, "every gallery view is captured").toEqual([]);
  });
};
