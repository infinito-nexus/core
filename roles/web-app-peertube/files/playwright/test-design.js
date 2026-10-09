const fs = require("fs");
const path = require("path");
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
const { apiFetchOnion, apiGetOnion, decodeDotenvQuotedValue, gotoOnion, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const ROOT_USERNAME = "root";
const SHOWCASE_VIDEO = "Design showcase";
const SHOWCASE_CHANNEL = "design_showcase";
const SHOWCASE_PLAYLIST = "Design showcase playlist";
const SIGNED_IN = "my-header .logged-in-container";
const THEME_TOKENS = {
  primaryColor: "--design-primary",
  onPrimaryColor: "--design-on-primary",
  foregroundColor: "--design-text",
  backgroundColor: "--design-surface-1",
  backgroundSecondaryColor: "--design-surface-3",
  menuForegroundColor: "--design-text",
  menuBackgroundColor: "--design-surface-2",
  headerForegroundColor: "--design-text",
  headerBackgroundColor: "--design-surface-1",
};

const ADMIN_PASSWORD = requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD");
const DESIGN_LOGO_URL = decodeDotenvQuotedValue(process.env.DESIGN_LOGO_URL || "");
const DESIGN_TITLE = decodeDotenvQuotedValue(process.env.DESIGN_TITLE || "");

function baseUrl() {
  return decodeDotenvQuotedValue(process.env.PEERTUBE_BASE_URL || "").replace(/\/$/, "");
}

let cachedHeaders = null;

async function api(request, url, options = {}) {
  let response = null;
  await expect
    .poll(
      async () => {
        response = options.method
          ? await apiFetchOnion(request, url, options)
          : await apiGetOnion(request, url, options);
        return ![429, 502, 503, 504].includes(response.status());
      },
      {
        message: `${url} must answer once PeerTube is up and outside its API rate limit`,
        intervals: [2_000, 5_000],
        timeout: resolveTimeout(60_000),
      },
    )
    .toBe(true);
  return response;
}

async function rootHeaders(request) {
  if (cachedHeaders) return cachedHeaders;
  const base = baseUrl();
  const client = await (await api(request, `${base}/api/v1/oauth-clients/local`)).json();
  const response = await api(request, `${base}/api/v1/users/token`, {
    method: "POST",
    form: {
      client_id: client.client_id,
      client_secret: client.client_secret,
      grant_type: "password",
      username: ROOT_USERNAME,
      password: ADMIN_PASSWORD,
    },
  });
  expect(response.status(), "root must obtain an API token with the administrator password").toBe(200);
  cachedHeaders = { Authorization: `Bearer ${(await response.json()).access_token}` };
  await api(request, `${base}/api/v1/users/me`, {
    method: "PUT",
    headers: cachedHeaders,
    data: { noWelcomeModal: true, noInstanceConfigWarningModal: true, noAccountSetupWarningModal: true },
  });
  return cachedHeaders;
}

async function signInRoot(page) {
  await rootHeaders(page.request);
  await gotoOnion(page, `${baseUrl()}/login`);
  const username = page.locator("#username");
  const password = page.locator("#password");
  await expect(username).toBeEditable({ timeout: resolveTimeout(10_000) });
  await username.fill(ROOT_USERNAME);
  await expect(password).toBeEditable({ timeout: resolveTimeout(10_000) });
  await password.fill(ADMIN_PASSWORD);
  await page.locator('input[type="submit"].primary-button').click();
  await expect(page.locator(SIGNED_IN)).toBeAttached({ timeout: resolveTimeout(10_000) });
}

async function awaitView(page, selector) {
  const target = page.locator(selector).first();
  const shown = await target.waitFor({ state: "visible", timeout: resolveTimeout(10_000) }).then(
    () => true,
    () => false,
  );
  if (!shown) {
    await page.waitForTimeout(resolveTimeout(10_000));
    await gotoOnion(page, page.url());
    await expect(target, `${selector} must render once PeerTube's API rate limit window has passed`).toBeVisible({
      timeout: resolveTimeout(10_000),
    });
  }
  await page.waitForTimeout(resolveTimeout(2_000));
}

async function seedShowcase(request) {
  const base = baseUrl();
  const headers = await rootHeaders(request);
  let channel = await api(request, `${base}/api/v1/video-channels/${SHOWCASE_CHANNEL}`, { headers });
  if (channel.status() === 404) {
    await api(request, `${base}/api/v1/video-channels`, {
      method: "POST",
      headers,
      data: { name: SHOWCASE_CHANNEL, displayName: "Design showcase channel" },
    });
    channel = await api(request, `${base}/api/v1/video-channels/${SHOWCASE_CHANNEL}`, { headers });
  }
  const channelId = (await channel.json()).id;
  const mine = await (
    await api(request, `${base}/api/v1/users/me/videos?search=${encodeURIComponent(SHOWCASE_VIDEO)}`, { headers })
  ).json();
  let video = mine.data.find((entry) => entry.name === SHOWCASE_VIDEO);
  if (!video) {
    const upload = await api(request, `${base}/api/v1/videos/upload`, {
      method: "POST",
      headers,
      multipart: {
        videofile: {
          name: "video_short.mp4",
          mimeType: "video/mp4",
          buffer: fs.readFileSync(path.join(__dirname, "fixtures", "video_short.mp4")),
        },
        channelId: String(channelId),
        name: SHOWCASE_VIDEO,
        privacy: "1",
        waitTranscoding: "false",
        description: "A short clip that shows the corporate design of the video platform.",
      },
    });
    expect(upload.ok(), "the showcase video upload must succeed").toBe(true);
    video = (await upload.json()).video;
  }
  const full = await (await api(request, `${base}/api/v1/videos/${video.uuid}`, { headers })).json();
  const threads = await (await api(request, `${base}/api/v1/videos/${full.uuid}/comment-threads`)).json();
  if (threads.total === 0) {
    await api(request, `${base}/api/v1/videos/${full.uuid}/comment-threads`, {
      method: "POST",
      headers,
      data: { text: "Reviewing the corporate design in light and dark mode." },
    });
  }
  const playlists = await (
    await api(request, `${base}/api/v1/accounts/${ROOT_USERNAME}/video-playlists?count=100`, { headers })
  ).json();
  let playlist = playlists.data.find((entry) => entry.displayName === SHOWCASE_PLAYLIST);
  if (!playlist) {
    const created = await api(request, `${base}/api/v1/video-playlists`, {
      method: "POST",
      headers,
      multipart: { displayName: SHOWCASE_PLAYLIST, privacy: "1", videoChannelId: String(channelId) },
    });
    playlist = (await created.json()).videoPlaylist;
    await api(request, `${base}/api/v1/video-playlists/${playlist.id}/videos`, {
      method: "POST",
      headers,
      data: { videoId: full.id },
    });
  }
  return { video: full, playlist };
}

exports.register = function () {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await gotoOnion(page, `${baseUrl()}/videos/browse`);
    await assertDesignTokens(page, "peertube");
  });

  test("design: PeerTube's theme configuration carries the palette tokens", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const config = await (await api(page.request, `${baseUrl()}/api/v1/config`)).json();
    for (const [key, token] of Object.entries(THEME_TOKENS)) {
      expect(config.theme.customization[key], `theme.customization.${key}`).toBe(`var(${token})`);
    }
    expect(config.instance.customizations.css, "the instance custom CSS must carry the token mapping").toContain(
      "--design-surface-1",
    );
  });

  test("design: page, primary action, header and text follow the tokens", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await api(page.request, `${baseUrl()}/api/v1/config`);
    await gotoOnion(page, `${baseUrl()}/login`);
    const submit = 'input[type="submit"].primary-button';
    await expect(page.locator(submit)).toBeVisible({ timeout: resolveTimeout(10_000) });
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      await assertToken(page, "body", "background-color", "--design-surface-1", `peertube ${mode}`);
      await assertToken(page, "body", "color", "--design-text", `peertube ${mode}`);
      await assertToken(page, submit, "background-color", "--design-primary", `peertube ${mode}`);
      await assertToken(page, submit, "color", "--design-on-primary", `peertube ${mode}`);
      await assertToken(page, "my-header .root", "background-color", "--design-surface-1", `peertube ${mode}`);
      await assertToken(page, ".main-menu", "background-color", "--design-surface-2", `peertube ${mode}`);
      await assertToken(page, "#username", "border-color", "--design-border-strong", `peertube ${mode}`);
    }
    await page.emulateMedia({ colorScheme: null });
    await assertLightAndDark(page, "body", "peertube");
    await assertLightAndDark(page, ".main-menu", "peertube menu");
    await assertReadable(page, ["body", "h1", "#username", submit, ".main-menu a"], "peertube");
  });

  test("design: a content divider uses the border token in both modes", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await signInRoot(page);
    const heading = page.locator("table thead th").first();
    for (const load of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: load });
      await gotoOnion(page, `${baseUrl()}/admin/overview/users/list`);
      await expect(heading).toBeVisible({ timeout: resolveTimeout(10_000) });
      for (const mode of ["light", "dark"]) {
        await page.emulateMedia({ colorScheme: mode });
        await expect
          .poll(() => heading.evaluate((element) => getComputedStyle(element).borderBottomColor), {
            message: `peertube loaded ${load}, shown ${mode}: the table head divider must equal --design-border`,
          })
          .toBe(await tokenValue(page, "--design-border", "color"));
      }
    }
    await page.locator("my-header .logged-in-container button").first().click();
    const divider = page.locator(".dropdown-menu.show .dropdown-divider").first();
    await expect(divider).toBeAttached({ timeout: resolveTimeout(10_000) });
    for (const mode of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: mode });
      await expect
        .poll(() => divider.evaluate((element) => getComputedStyle(element).borderTopColor), {
          message: `peertube ${mode}: the account menu divider must equal --design-border`,
        })
        .toBe(await tokenValue(page, "--design-border", "color"));
    }
    await page.emulateMedia({ colorScheme: null });
  });

  test("design: an explicit interface theme overrides the browser preference", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    const base = baseUrl();
    await signInRoot(page);
    const headers = await rootHeaders(page.request);
    const storeTheme = async (theme) => {
      const response = await api(page.request, `${base}/api/v1/users/me`, {
        method: "PUT",
        headers,
        data: { theme },
      });
      expect(response.ok(), `storing the interface theme ${theme}`).toBe(true);
    };
    try {
      await page.emulateMedia({ colorScheme: "light" });
      await gotoOnion(page, `${base}/my-account/settings`);
      await expect(page.locator(SIGNED_IN)).toBeAttached({ timeout: resolveTimeout(10_000) });
      const lightSurface = await tokenValue(page, "--design-surface-1", "background-color");

      await storeTheme("peertube-core-dark-brown");
      await gotoOnion(page, `${base}/my-account/settings`);
      await expect(page.locator("html")).toHaveAttribute("data-pt-theme", "peertube-core-dark-brown", {
        timeout: resolveTimeout(10_000),
      });
      await expect(page.locator("html")).toHaveAttribute("data-design-theme", "dark");
      expect(await tokenValue(page, "--design-surface-1", "background-color")).not.toBe(lightSurface);
      await assertToken(page, "body", "background-color", "--design-surface-1", "peertube explicit dark");

      await page.emulateMedia({ colorScheme: "dark" });
      await storeTheme("peertube-core-light-beige");
      await gotoOnion(page, `${base}/my-account/settings`);
      await expect(page.locator("html")).toHaveAttribute("data-design-theme", "light", {
        timeout: resolveTimeout(10_000),
      });
      expect(await tokenValue(page, "--design-surface-1", "background-color")).toBe(lightSurface);
      await assertToken(page, "body", "background-color", "--design-surface-1", "peertube explicit light");
    } finally {
      await storeTheme("instance-default");
      await page.emulateMedia({ colorScheme: null });
    }
  });

  test("design: PeerTube serves the corporate logo and title", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!DESIGN_LOGO_URL && !DESIGN_TITLE, "logo and title replacement are disabled for this role");
    const base = baseUrl();
    if (DESIGN_LOGO_URL) {
      const config = await (await api(page.request, `${base}/api/v1/config`)).json();
      for (const type of ["header-wide", "header-square", "favicon"]) {
        const entry = config.instance.logo.find((logo) => logo.type === type);
        expect(entry.isFallback, `an uploaded ${type} logo must replace the PeerTube fallback`).toBe(false);
        const served = await api(page.request, entry.fileUrl);
        expect(
          served.headers()["content-type"],
          `PeerTube must serve the ${type} logo as the raster the role uploads; its SVG sanitizer drops the embedded symbol`,
        ).toBe("image/png");
      }
      const wide = config.instance.logo.find((logo) => logo.type === "header-wide");
      const generated = await apiGetOnion(page.request, DESIGN_LOGO_URL);
      expect(generated.ok(), "the generated lockup is published on the CDN").toBe(true);
      const pngSize = (buffer) => [buffer.readUInt32BE(16), buffer.readUInt32BE(20)];
      expect(
        pngSize(await (await api(page.request, wide.fileUrl)).body()),
        "PeerTube must serve the generated lockup at its own size",
      ).toEqual(pngSize(await generated.body()));
      await page.setViewportSize({ width: 1440, height: 900 });
      await gotoOnion(page, `${base}/videos/browse`);
      const logo = page.locator("my-header img.logo");
      await expect(logo).toBeVisible({ timeout: resolveTimeout(10_000) });
      await expect(logo).toHaveAttribute("src", wide.fileUrl);
      await expect.poll(() => logo.evaluate((image) => image.naturalWidth)).toBeGreaterThan(0);
      const box = await logo.boundingBox();
      expect(box.width, "the header lockup must be wider than high").toBeGreaterThan(box.height * 2);
      await expect(page.locator("my-header .instance-name"), "the lockup carries the title").toHaveCount(0);
    }
    if (DESIGN_TITLE) {
      await gotoOnion(page, `${base}/videos/browse`);
      await expect(page).toHaveTitle(new RegExp(DESIGN_TITLE), { timeout: resolveTimeout(10_000) });
    }
  });

  test("design: gallery of visitor, account and administration views", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(1_500_000));
    const base = baseUrl();
    const showcase = await seedShowcase(page.request);
    const view = (name, url, ready) => ({
      name,
      url: `${base}${url}`,
      prepare: (current) => awaitView(current, ready),
    });
    const failures = [];
    await captureDesignGallery(page, [
      view("browse-videos", "/videos/browse", "my-video-miniature"),
      view("login", "/login", "#username"),
      view("about-instance", "/about/instance/home", "my-about-instance"),
      view("search", `/search?search=${encodeURIComponent("Design")}`, "my-video-miniature"),
      view("video-watch", `/w/${showcase.video.shortUUID}`, ".video-info-name"),
      view("channel-videos", `/c/${SHOWCASE_CHANNEL}/videos`, "my-video-miniature"),
      view("playlist-watch", `/w/p/${showcase.playlist.shortUUID}`, ".video-info-name"),
      {
        name: "quick-settings",
        url: `${base}/videos/browse`,
        prepare: async (current) => {
          await awaitView(current, "my-header .settings-button");
          await current.locator("my-header .settings-button").first().click();
          const modal = current.locator(".modal.show .modal-content");
          await expect(modal).toBeVisible({ timeout: resolveTimeout(10_000) });
          await expect
            .poll(() => modal.evaluate((element) => getComputedStyle(element.closest(".modal")).opacity), {
              timeout: resolveTimeout(10_000),
            })
            .toBe("1");
        },
      },
    ]).catch((error) => failures.push(error.message));

    await signInRoot(page);
    await captureDesignGallery(page, [
      view("account-settings", "/my-account/settings", "form"),
      view("account-notifications", "/my-account/notifications", "my-user-notifications"),
      view("library-videos", "/my-library/videos", "my-video-cell"),
      view("library-channels", "/my-library/video-channels", "my-edit-button"),
      view("library-playlists", "/my-library/video-playlists", "my-video-playlist-miniature"),
      view("playlist-create", "/my-library/video-playlists/create", "form"),
      view("video-publish", "/videos/publish", "input[type=file]"),
      view("video-manage", `/videos/manage/${showcase.video.uuid}`, "input#name"),
      view("admin-users", "/admin/overview/users/list", "table tbody td"),
      view("admin-user-create", "/admin/overview/users/create", "form"),
      view("admin-videos", "/admin/overview/videos/list", "table tbody td"),
      view("admin-comments", "/admin/overview/comments/list", "table tbody td"),
      view("admin-config-information", "/admin/settings/config/information", "form"),
      view("admin-config-customization", "/admin/settings/config/customization", "form"),
      view("admin-config-logo", "/admin/settings/config/logo", "my-admin-config-logo"),
      view("admin-config-general", "/admin/settings/config/general", "form"),
      view("admin-plugins", "/admin/settings/plugins/list-installed", "my-plugin-list-installed"),
      view("admin-jobs", "/admin/settings/system/jobs", "table"),
      {
        name: "user-menu",
        url: `${base}/my-library/videos`,
        prepare: async (current) => {
          await awaitView(current, "my-video-cell");
          await current.locator("my-header .logged-in-container button").first().click();
          const menu = current.locator("[ngbdropdownmenu].show, .dropdown-menu.show").first();
          await expect(menu).toBeVisible({ timeout: resolveTimeout(10_000) });
          await expect
            .poll(() => menu.evaluate((element) => getComputedStyle(element).opacity), {
              timeout: resolveTimeout(10_000),
            })
            .toBe("1");
        },
      },
    ]).catch((error) => failures.push(error.message));
    expect(failures, `design gallery failures:\n${failures.join("\n")}`).toEqual([]);
  });
};
