// SeaweedFS object-store scenario for Nextcloud.
//
// Nextcloud is configured with S3 primary storage (OBJECTSTORE_S3_*), so every
// file uploaded through the Files app is written to the consumer bucket as a
// `urn:oid:<id>` object. The action logs the administrator in and uploads a
// file; the shared check proves the bucket grew via the Filer UI.

const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { runSeaweedfsStorageCheck } = require("./personas");
const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

test("seaweedfs: an uploaded Nextcloud file is stored in the SeaweedFS bucket", async ({ page, browser }) => {
  skipUnlessServiceEnabled("seaweedfs");
  test.setTimeout(180_000);

  await runSeaweedfsStorageCheck(page, browser, {
    label: "a Nextcloud Files upload",
    action: async (appPage) => {
      await shared.loginToStandaloneNextcloud(appPage);

      const filesUrl = new URL("apps/files/", shared.env.nextcloudBaseUrl).toString();
      await appPage.goto(filesUrl, { waitUntil: "domcontentloaded" });
      await shared.dismissBlockingNextcloudModals(appPage, appPage);

      const markerBase = `infinito-storage-check-${Date.now()}`;
      const marker = `${markerBase}.txt`;
      await appPage
        .locator('input[type="file"]')
        .first()
        .setInputFiles({
          name: marker,
          mimeType: "text/plain",
          buffer: Buffer.from(`infinito storage check ${marker}`),
        });

      // Nextcloud renders the basename and the extension as separate nodes, so
      // match the basename (a single text node).
      await expect(
        appPage.getByText(markerBase, { exact: false }).first(),
        `the uploaded file '${marker}' must appear in the Nextcloud Files listing`,
      ).toBeVisible({ timeout: 30_000 });
    },
  });
});
