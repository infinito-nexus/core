// SeaweedFS object-store scenario for Open WebUI.
//
// Open WebUI is configured with S3 file storage (env.j2: STORAGE_PROVIDER=s3 +
// S3_BUCKET_NAME/S3_ENDPOINT_URL/S3_ACCESS_KEY_ID/S3_SECRET_ACCESS_KEY/
// S3_REGION_NAME from the `objstore` lookup, which resolves to SeaweedFS when
// seaweedfs is the enabled engine). With STORAGE_PROVIDER=s3 the file-upload
// pipeline (POST /api/v1/files/) persists every raw uploaded file into the
// consumer bucket instead of the local volume. The simplest user action that
// triggers that upload is attaching a document to a chat: selecting a file in
// the message composer immediately uploads it through /api/v1/files/, which
// writes the object to S3. The action signs the administrator in over OIDC
// (mirroring playwright.spec.js via the shared signInViaDashboardOidc flow),
// attaches a small text document, and the shared check proves the bucket grew
// via the Filer UI.

const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { runSeaweedfsStorageCheck } = require("./personas");
const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

test("seaweedfs: an uploaded Open WebUI document is stored in the SeaweedFS bucket", async ({ page, browser }) => {
  skipUnlessServiceEnabled("seaweedfs");
  test.setTimeout(180_000);

  await runSeaweedfsStorageCheck(page, browser, {
    label: "an Open WebUI chat document upload",
    action: async (appPage) => {
      const baseUrl = shared.env.openwebuiBaseUrl.replace(/\/$/, "");

      await appPage.context().clearCookies();
      await shared.signInViaDashboardOidc(
        appPage,
        shared.env.adminUsername,
        shared.env.adminPassword,
        "administrator",
      );

      await appPage.goto(`${baseUrl}/`, { waitUntil: "domcontentloaded" });
      await shared.dismissAllOpenModals(appPage);

      const markerBase = `infinito-storage-check-${Date.now()}`;
      const marker = `${markerBase}.txt`;

      const fileInput = appPage
        .locator("input[type='file'][accept], input[type='file'][multiple], input[type='file']")
        .first();
      await fileInput.waitFor({ state: "attached", timeout: 60_000 });
      await fileInput.setInputFiles({
        name: marker,
        mimeType: "text/plain",
        buffer: Buffer.from(`infinito storage check ${marker}`),
      });

      await expect(
        appPage.getByText(markerBase, { exact: false }).first(),
        `the attached document '${marker}' must appear in the Open WebUI composer after upload`,
      ).toBeVisible({ timeout: 60_000 });
    },
  });
});
