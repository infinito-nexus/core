const { test } = require("@playwright/test");

const { assertDesignTokens, captureDesignGallery, galleryEnabled } = require("./design");
const { decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const SHOWCASE_REPO = "design-showcase";

function env(name) {
  return decodeDotenvQuotedValue(process.env[name]);
}

function baseUrl() {
  return env("APP_BASE_URL").replace(/\/$/, "");
}

async function signIn(page, base, username, password) {
  await gotoOnion(page, `${base}/user/login`);
  await page.locator("#user_name").fill(username);
  await page.locator("#password").fill(password);
  await page.locator("#password").press("Enter");
  await page.waitForURL((url) => !url.pathname.startsWith("/user/login"), {
    timeout: resolveTimeout(60_000),
  });
}

async function seedShowcase(page, base, username, password) {
  const headers = {
    Authorization: `Basic ${Buffer.from(`${username}:${password}`).toString("base64")}`,
  };
  await page.request.post(`${base}/api/v1/user/repos`, {
    headers,
    data: { name: SHOWCASE_REPO, auto_init: true, readme: "Default", description: "Corporate design showcase" },
    failOnStatusCode: false,
  });
  const issues = await page.request.get(`${base}/api/v1/repos/${username}/${SHOWCASE_REPO}/issues?state=all`, {
    headers,
  });
  if ((await issues.json()).length === 0) {
    await page.request.post(`${base}/api/v1/repos/${username}/${SHOWCASE_REPO}/issues`, {
      headers,
      data: {
        title: "Review the corporate design",
        body: "- [ ] Light mode\n- [ ] Dark mode\n- [ ] Mobile layout",
      },
    });
  }
}

exports.register = function () {
  test("design: corporate tokens apply in light and dark mode", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    await gotoOnion(page, `${baseUrl()}/`);
    await assertDesignTokens(page, "gitea");
  });

  test("design: gallery of public, user and administration views", async ({ page }) => {
    skipUnlessServiceEnabled("design");
    test.skip(!galleryEnabled(), "INFINITO_PLAYWRIGHT_KEEP is not true");
    test.setTimeout(resolveTimeout(900_000));
    const base = baseUrl();
    const username = env("ADMIN_USERNAME");
    const password = env("ADMIN_PASSWORD");

    await captureDesignGallery(page, [
      { name: "start", url: `${base}/` },
      { name: "login", url: `${base}/user/login` },
      { name: "explore-repos", url: `${base}/explore/repos` },
      { name: "explore-users", url: `${base}/explore/users` },
    ]);

    await signIn(page, base, username, password);
    await seedShowcase(page, base, username, password);
    const repo = `${base}/${username}/${SHOWCASE_REPO}`;

    await captureDesignGallery(page, [
      { name: "dashboard", url: `${base}/` },
      { name: "repo-create", url: `${base}/repo/create` },
      { name: "org-create", url: `${base}/org/create` },
      { name: "repo-home", url: repo },
      { name: "repo-file", url: `${repo}/src/branch/main/README.md` },
      { name: "repo-commits", url: `${repo}/commits/branch/main` },
      { name: "repo-branches", url: `${repo}/branches` },
      { name: "repo-issues", url: `${repo}/issues` },
      { name: "issue-detail", url: `${repo}/issues/1` },
      { name: "issue-new", url: `${repo}/issues/new` },
      { name: "repo-pulls", url: `${repo}/pulls` },
      { name: "repo-labels", url: `${repo}/labels` },
      { name: "repo-milestones", url: `${repo}/milestones` },
      { name: "repo-wiki", url: `${repo}/wiki` },
      { name: "repo-settings", url: `${repo}/settings` },
      { name: "user-profile", url: `${base}/${username}` },
      { name: "settings-profile", url: `${base}/user/settings` },
      { name: "settings-account", url: `${base}/user/settings/account` },
      { name: "settings-appearance", url: `${base}/user/settings/appearance` },
      { name: "settings-security", url: `${base}/user/settings/security` },
      { name: "settings-keys", url: `${base}/user/settings/keys` },
      { name: "admin-dashboard", url: `${base}/-/admin` },
      { name: "admin-users", url: `${base}/-/admin/users` },
      { name: "admin-repos", url: `${base}/-/admin/repos` },
      { name: "admin-config", url: `${base}/-/admin/config` },
    ]);
  });
};
