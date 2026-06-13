// SeaweedFS object-store scenario for BookWyrm.
//
// BookWyrm is configured with django-storages S3 (USE_S3=true / AWS_* in
// templates/env.j2), so user-uploaded images — avatars, book covers — are
// written to the consumer bucket instead of the local media root. The action
// logs the administrator in through the oauth2-proxy / Keycloak gate (the same
// inline flow the role's playwright.spec.js uses) and sets the profile avatar
// from /preferences/profile; the shared check proves the bucket grew via the
// Filer UI.

const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const {
  runSeaweedfsStorageCheck,
  performKeycloakLoginForm,
  normalizeBaseUrl,
  decodeDotenvQuotedValue,
} = require("./personas");

test.use({ ignoreHTTPSErrors: true });

const PNG_AVATAR_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAIAAAD/gAIDAAAA60lEQVR4nO3QQQ3AIADAQEDh5CAHqbOwvsiSOwVN537O4Jt1O+BPzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCl7E6QIw0tiFNgAAAABJRU5ErkJggg==";

test("seaweedfs: a BookWyrm avatar upload is stored in the SeaweedFS bucket", async ({ page, browser }) => {
  skipUnlessServiceEnabled("seaweedfs");
  test.setTimeout(180_000);

  const baseUrl = normalizeBaseUrl(process.env.BOOKWYRM_BASE_URL || "");
  const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
  const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");

  await runSeaweedfsStorageCheck(page, browser, {
    label: "a BookWyrm profile-avatar upload",
    action: async (appPage) => {
      expect(baseUrl, "BOOKWYRM_BASE_URL must be set").toBeTruthy();
      expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
      expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();

      await appPage.context().clearCookies();
      await appPage.goto(`${baseUrl}/`, { waitUntil: "domcontentloaded" });

      if (/openid-connect\/auth|\/oauth2\//.test(appPage.url())) {
        await performKeycloakLoginForm(appPage, adminUsername, adminPassword);
        await expect
          .poll(() => appPage.url(), { timeout: 90_000 })
          .toContain(baseUrl.replace(/^https?:\/\//, ""));
      }

      await appPage.goto(`${baseUrl}/preferences/profile`, { waitUntil: "domcontentloaded" });

      const avatarInput = appPage
        .locator('input[type="file"][name="avatar"]')
        .or(appPage.locator('input[type="file"]'))
        .first();
      await avatarInput.waitFor({ state: "attached", timeout: 30_000 });
      await avatarInput.setInputFiles({
        name: `infinito-storage-check-${Date.now()}.png`,
        mimeType: "image/png",
        buffer: Buffer.from(PNG_AVATAR_BASE64, "base64"),
      });

      const saveButton = appPage
        .locator('form[name="edit-profile"]')
        .getByRole("button", { name: /save/i })
        .first();
      await saveButton.click();

      // BookWyrm's EditUser view redirects to the user feed on a valid save and
      // re-renders /preferences/profile (HTTP 200) on a validation failure. The
      // body stays visible either way, so assert we actually left the edit form
      // — that is the only signal the avatar POST was accepted and an object was
      // written to S3.
      await expect
        .poll(() => appPage.url(), { timeout: 60_000 })
        .not.toContain("/preferences/profile");
      await appPage.waitForLoadState("networkidle", { timeout: 60_000 }).catch(() => {});
    },
  });
});
