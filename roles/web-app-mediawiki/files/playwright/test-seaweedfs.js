// SeaweedFS object-store scenario for MediaWiki.
//
// Extension:AWS replaces $wgLocalFileRepo with the AmazonS3FileBackend, so a
// file a logged-in user sends through Special:Upload is written straight to
// the consumer bucket as a new object named after the destination title
// ($wgAWSRepoHashLevels stays at its default 0, so the key is the title).
//
// The wiki has no local login form ($wgPluggableAuth_EnableLocalLogin is
// false), so the upload needs the Keycloak round-trip and the scenario is
// gated on sso as well as on seaweedfs. The generic biber persona journey
// stays blocked for an unrelated reason (see the role README), which is why
// this spec does not consult PERSONA_BIBER_BLOCKED.
//
// Required env (rendered by templates/playwright.env.j2):
//   APP_BASE_URL, CANONICAL_DOMAIN, BIBER_USERNAME, BIBER_PASSWORD and the
//   SEAWEEDFS_* keys consumed by runSeaweedfsStorageCheck.

const { test, expect } = require("@playwright/test");
const { resolveTimeout, isOnionTarget } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { normalizeUrl, readEnv, performKeycloakLogin, clickOidcLoginLink, runSeaweedfsStorageCheck } = require("./personas");

const UPLOAD_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
);

test.use({ ignoreHTTPSErrors: true });

test("seaweedfs: a file uploaded through Special:Upload is stored in the SeaweedFS bucket", async ({ page, browser }) => {
  test.skip(isOnionTarget(), "the S3 API is served under the canonical domain, not as an onion surface (headless backend)");
  skipUnlessServiceEnabled("seaweedfs");
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(300_000));

  const appBaseUrl = normalizeUrl(process.env.APP_BASE_URL);
  const canonicalDomain = readEnv("CANONICAL_DOMAIN");
  const biberUsername = readEnv("BIBER_USERNAME");
  const biberPassword = readEnv("BIBER_PASSWORD");

  await runSeaweedfsStorageCheck(page, browser, {
    label: "a MediaWiki Special:Upload file upload",
    action: async (appPage) => {
      const base = appBaseUrl.replace(/\/$/, "");
      await appPage.goto(`${base}/index.php?title=Special:UserLogin&returnto=Special:Upload`, {
        waitUntil: "domcontentloaded",
      });
      await appPage
        .waitForLoadState("networkidle", { timeout: resolveTimeout(30_000) })
        .catch(() => {});

      let authPage = appPage;
      if (!appPage.url().includes("openid-connect/auth")) {
        const strictLogin = appPage
          .getByRole("link", { name: /^\s*(log\s*in|sign\s*in|sso)\s*$/i })
          .or(appPage.getByRole("button", { name: /^\s*(log\s*in|sign\s*in|sso)\s*$/i }))
          .first();
        const looseLogin = appPage
          .getByRole("link", { name: /log\s*in|sign\s*in|sso/i })
          .or(appPage.getByRole("button", { name: /log\s*in|sign\s*in|sso/i }))
          .first();
        authPage = (await clickOidcLoginLink(appPage, strictLogin, looseLogin)) || appPage;
      }
      expect(
        authPage.url().includes("openid-connect/auth"),
        "the wiki never handed Special:UserLogin off to the Keycloak authorize endpoint, so the " +
          `upload below would run anonymously. Current URL: ${authPage.url()}.`,
      ).toBe(true);
      await performKeycloakLogin(authPage, biberUsername, biberPassword, canonicalDomain);

      await appPage.goto(`${base}/index.php?title=Special:Upload`, { waitUntil: "domcontentloaded" });

      const destFile = `Infinito-storage-check-${Date.now()}.png`;
      const fileInput = appPage.locator('input[type="file"][name="wpUploadFile"]').first();
      await expect(
        fileInput,
        "Special:Upload must expose the wpUploadFile input; its absence means $wgEnableUploads is false " +
          "or the signed-in account holds no 'upload' right",
      ).toBeAttached({ timeout: resolveTimeout(60_000) });

      await fileInput.setInputFiles({
        name: destFile,
        mimeType: "image/png",
        buffer: UPLOAD_PNG,
      });
      await appPage.locator('input[name="wpDestFile"]').first().fill(destFile);
      await appPage.locator('input[name="wpIgnoreWarning"]').first().check({ force: true });

      await appPage.locator('button[name="wpUpload"], input[name="wpUpload"]').first().click();
      await appPage.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(60_000) }).catch(() => {});

      await expect(
        appPage.locator("body"),
        `MediaWiki never rendered the File page for ${destFile}, so Special:Upload rejected the file ` +
          "before the S3 backend was reached",
      ).toContainText(destFile, { timeout: resolveTimeout(60_000) });
    },
  });
});
