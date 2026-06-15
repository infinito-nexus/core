// SeaweedFS object-store scenario for Matrix Synapse.
//
// Synapse is configured with the synapse-s3-storage-provider media storage
// provider (flavor/ansible/vars.yml.j2:
// matrix_synapse_ext_synapse_s3_storage_provider_enabled=true,
// store_synchronous=true, config_endpoint_url pointed at the SeaweedFS S3
// gateway), so a media file a user uploads through Element's
// /_matrix/media/v3/upload endpoint is mirrored into the consumer bucket as a
// new object the moment Synapse stores it. The action signs the administrator
// into Element and sets a profile avatar; the avatar PNG is uploaded as a
// Synapse media object, and the shared check proves the bucket grew via the
// Filer UI.
//
// Required env (rendered by templates/playwright.env.j2):
//   ELEMENT_BASE_URL, OIDC_ISSUER_URL, the admin login vars consumed by
//   signInViaElement, and the SEAWEEDFS_* keys consumed by
//   runSeaweedfsStorageCheck.

const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { runSeaweedfsStorageCheck } = require("./personas");
const shared = require("./_shared");

const AVATAR_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
);

test.use({ ignoreHTTPSErrors: true });

test("seaweedfs: an uploaded Matrix avatar is stored in the SeaweedFS bucket", async ({ page, browser }) => {
  skipUnlessServiceEnabled("seaweedfs");
  test.setTimeout(600_000);

  await runSeaweedfsStorageCheck(page, browser, {
    label: "a Matrix profile avatar upload",
    action: async (appPage) => {
      await shared.installCspViolationObserver(appPage);
      await shared.signInViaElement(
        appPage,
        shared.env.adminUsername,
        shared.env.adminPassword,
        "administrator",
      );

      const elementBaseUrl = shared.env.elementBaseUrl.replace(/\/$/, "");
      await appPage.goto(`${elementBaseUrl}/#/settings`, { waitUntil: "domcontentloaded" });

      const fileInput = appPage
        .locator('input[type="file"][accept*="image" i], .mx_AvatarSetting input[type="file"], input[type="file"]')
        .first();
      await expect(
        fileInput,
        "Element user settings must expose a file input to set a profile avatar",
      ).toBeAttached({ timeout: 60_000 });

      const marker = `infinito-storage-check-${Date.now()}.png`;
      await fileInput.setInputFiles({
        name: marker,
        mimeType: "image/png",
        buffer: AVATAR_PNG,
      });

      const saveButton = appPage
        .getByRole("button", { name: /^(save|apply|upload|confirm)$/i })
        .first();
      if (await saveButton.isVisible({ timeout: 10_000 }).catch(() => false)) {
        await saveButton.click().catch(() => {});
      }
    },
  });
});
