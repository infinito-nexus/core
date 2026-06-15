// SeaweedFS object-store scenario for Penpot.
//
// Penpot is configured with S3 asset storage (env.j2:
// PENPOT_ASSETS_STORAGE_BACKEND=assets-s3 / PENPOT_STORAGE_ASSETS_S3_BUCKET),
// so an image uploaded as a design asset is written to the consumer bucket as
// a new object. The action signs the administrator in via the in-app OpenID
// entry (Keycloak), opens a fresh Drafts file in the workspace editor and
// uploads a small PNG; the shared check proves the bucket grew via the Filer
// UI. Login reuses the suite's `penpotOidcLogin` helper from `./_shared`.

const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { runSeaweedfsStorageCheck } = require("./personas");
const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

test("seaweedfs: an uploaded Penpot image asset is stored in the SeaweedFS bucket", async ({ page, browser }) => {
  skipUnlessServiceEnabled("seaweedfs");
  test.setTimeout(180_000);

  await runSeaweedfsStorageCheck(page, browser, {
    label: "a Penpot image asset upload",
    action: async (appPage) => {
      await shared.penpotOidcLogin(appPage, shared.env.adminUsername, shared.env.adminPassword);

      await appPage.getByText("Drafts", { exact: true }).first().click();
      const newFile = appPage.getByText(/\+\s*New File/i).first();
      await expect(newFile, "Expected a create-file control in Drafts").toBeVisible({ timeout: 60_000 });
      await newFile.click();
      await expect
        .poll(() => appPage.url(), { timeout: 90_000, message: "expected to enter the Penpot workspace editor" })
        .toContain("/workspace");

      const validPng = shared.validImagePng();
      const markerBase = `infinito-storage-check-${Date.now()}`;
      const marker = `${markerBase}.png`;
      const fileInput = appPage.locator('input[type="file"]').first();
      await fileInput.waitFor({ state: "attached", timeout: 60_000 });
      await fileInput.setInputFiles({ name: marker, mimeType: "image/png", buffer: validPng });

      // Penpot names the created layer/asset after the uploaded basename
      // (extension stripped), so match the basename — a single, unique node —
      // rather than a loose `image` alternative that matches workspace chrome.
      await expect(
        appPage.getByText(markerBase, { exact: false }).first(),
        `the uploaded image asset '${marker}' must be acknowledged in the Penpot workspace`,
      ).toBeVisible({ timeout: 60_000 });
    },
  });
});
