// SeaweedFS object-store scenario for Decidim.
//
// Decidim is configured with ActiveStorage on the S3 service (env.j2:
// STORAGE_PROVIDER=s3, AWS_BUCKET/AWS_ENDPOINT/...; storage.yml patched with
// force_path_style: true), so a user-uploaded avatar is written to the
// consumer bucket. Decidim's account avatar control uses an ActiveStorage
// direct upload (modal file_field with direct_upload: true), so the moment the
// file is attached the blob is streamed straight to S3 — a new object lands in
// the bucket before the account form is even submitted. The action logs the
// administrator in via the native form and attaches a PNG avatar; the shared
// check proves the bucket grew via the Filer UI.

const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { runSeaweedfsStorageCheck, decodeDotenvQuotedValue } = require("./personas");

const PNG_64x64 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAATklEQVR42u3PQQkAAAgEsEtiZhtrBN/CYAWW6nktAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgKXBQhu0YfsD/UeAAAAAElFTkSuQmCC",
  "base64",
);

test.use({ ignoreHTTPSErrors: true });

test("seaweedfs: an uploaded Decidim avatar is stored in the SeaweedFS bucket", async ({ page, browser }) => {
  skipUnlessServiceEnabled("seaweedfs");
  test.setTimeout(180_000);

  const baseUrl = decodeDotenvQuotedValue(process.env.DECIDIM_BASE_URL || process.env.APP_BASE_URL).replace(/\/$/, "");
  const adminEmail = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL);
  const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);

  await runSeaweedfsStorageCheck(page, browser, {
    label: "a Decidim account avatar upload",
    action: async (appPage) => {
      expect(baseUrl, "DECIDIM_BASE_URL must be set for the Decidim seaweedfs check").toBeTruthy();
      expect(adminEmail, "ADMIN_EMAIL must be set for the Decidim seaweedfs check").toBeTruthy();
      expect(adminPassword, "ADMIN_PASSWORD must be set for the Decidim seaweedfs check").toBeTruthy();

      await appPage.goto(`${baseUrl}/users/sign_in`, { waitUntil: "domcontentloaded" });
      await appPage.waitForLoadState("networkidle").catch(() => {});

      const acceptCookies = appPage
        .getByRole("button", { name: /accept all|accept only essential|accept/i })
        .first();
      if (await acceptCookies.isVisible().catch(() => false)) {
        await acceptCookies.click().catch(() => {});
        await appPage.waitForLoadState("networkidle").catch(() => {});
      }

      const emailInput = appPage.getByLabel(/email/i).first();
      await emailInput.waitFor({ state: "attached", timeout: 60_000 });
      await emailInput.fill(adminEmail);
      await appPage.locator("input[type='password']").first().fill(adminPassword);
      await appPage.getByRole("button", { name: /log in|sign in/i }).first().click();
      await appPage.waitForLoadState("networkidle").catch(() => {});
      await expect(appPage, "the administrator must be signed in for the avatar upload").not.toHaveURL(/sign_in/);

      await appPage.goto(`${baseUrl}/account`, { waitUntil: "domcontentloaded" });
      await appPage.waitForLoadState("networkidle").catch(() => {});

      const openModal = appPage
        .locator('[data-upload] button, .upload-container button, [data-upload-modal]')
        .or(appPage.getByRole("button", { name: /avatar|add file|add image|edit image|replace image|upload|change/i }))
        .first();
      if (await openModal.isVisible({ timeout: 10_000 }).catch(() => false)) {
        await openModal.click().catch(() => {});
        await appPage.waitForLoadState("networkidle").catch(() => {});
      }

      const fileInput = appPage
        .locator('[data-upload] input[type="file"], .upload-modal input[type="file"], input[type="file"]')
        .first();
      await fileInput.waitFor({ state: "attached", timeout: 60_000 });

      const marker = `infinito-storage-check-${Date.now()}.png`;
      await fileInput.setInputFiles({ name: marker, mimeType: "image/png", buffer: PNG_64x64 });

      const saveModal = appPage.locator("[data-dropzone-save]").first();
      if (await saveModal.isVisible().catch(() => false)) {
        await expect(saveModal).toBeEnabled({ timeout: 60_000 });
        await saveModal.click().catch(() => {});
      }

      const updateAccount = appPage.getByRole("button", { name: /update account|update|save/i }).first();
      if (await updateAccount.isVisible().catch(() => false)) {
        await updateAccount.click().catch(() => {});
        await appPage.waitForLoadState("networkidle").catch(() => {});
      }
    },
  });
});
