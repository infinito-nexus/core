// SeaweedFS object-store scenario for Mastodon.
//
// Required env (rendered by templates/playwright.env.j2):
//   APP_BASE_URL, CANONICAL_DOMAIN, ADMIN_USERNAME, ADMIN_PASSWORD and the
//   SEAWEEDFS_* keys consumed by runSeaweedfsStorageCheck.

const { test, expect } = require("@playwright/test");
const { resolveTimeout, isOnionTarget } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { normalizeUrl, readEnv, performKeycloakLogin, clickOidcLoginLink, runSeaweedfsStorageCheck } = require("./personas");

const AVATAR_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
);

test.use({ ignoreHTTPSErrors: true });

test("seaweedfs: a saved Mastodon avatar is stored in the SeaweedFS bucket", async ({ page, browser }) => {
  test.skip(isOnionTarget(), "SeaweedFS filer UI is not a Tor surface on an onion node (headless backend)");
  skipUnlessServiceEnabled("seaweedfs");
  test.skip(
    (process.env.PERSONA_ADMINISTRATOR_BLOCKED || "").toLowerCase() === "true",
    "administrator persona is blocked by the role contract (PERSONA_ADMINISTRATOR_BLOCKED=true); this scenario drives the same admin journey.",
  );
  test.setTimeout(resolveTimeout(300_000));

  const appBaseUrl = normalizeUrl(process.env.APP_BASE_URL);
  const canonicalDomain = readEnv("CANONICAL_DOMAIN");
  const adminUsername = readEnv("ADMIN_USERNAME");
  const adminPassword = readEnv("ADMIN_PASSWORD");

  await runSeaweedfsStorageCheck(page, browser, {
    label: "a Mastodon profile avatar upload",
    action: async (appPage) => {
      const base = appBaseUrl.replace(/\/$/, "");
      await appPage.goto(`${base}/auth/sign_in`, { waitUntil: "domcontentloaded" });
      if (!appPage.url().includes("openid-connect/auth")) {
        const strictLogin = appPage
          .getByRole("link", { name: /^\s*(log\s*in|sign\s*in|sso)\s*$/i })
          .first();
        const looseLogin = appPage
          .getByRole("link", { name: /log\s*in|sign\s*in|sso/i })
          .first();
        await clickOidcLoginLink(appPage, strictLogin, looseLogin);
      }
      if (appPage.url().includes("openid-connect/auth")) {
        await performKeycloakLogin(appPage, adminUsername, adminPassword, canonicalDomain);
      }

      await appPage.goto(`${base}/settings/profile`, { waitUntil: "domcontentloaded" });

      const movedEditor = appPage.locator("a[href$='/profile/edit']").first();
      const editorMoved = await movedEditor
        .waitFor({ state: "attached", timeout: resolveTimeout(5_000) })
        .then(() => true)
        .catch(() => false);
      if (editorMoved) {
        await appPage.goto(`${base}/profile/edit`, { waitUntil: "domcontentloaded" });
      }

      const fileInput = appPage
        .locator('input#account_avatar, input[type="file"][name*="avatar" i], input[type="file"]')
        .first();
      await expect(
        fileInput,
        "the Mastodon profile editing page must expose an avatar file input",
      ).toBeAttached({ timeout: resolveTimeout(60_000) });

      await fileInput.setInputFiles({
        name: `infinito-storage-check-${Date.now()}.png`,
        mimeType: "image/png",
        buffer: AVATAR_PNG,
      });

      await appPage
        .getByRole("button", { name: /save changes|save|speichern/i })
        .or(appPage.locator('button[type="submit"], input[type="submit"]'))
        .first()
        .click();
      await appPage.waitForLoadState("networkidle", { timeout: resolveTimeout(60_000) }).catch(() => {});
    },
  });
});
