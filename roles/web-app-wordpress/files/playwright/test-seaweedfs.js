const { test, expect } = require("@playwright/test");
const { resolveTimeout, isOnionTarget } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { runSeaweedfsStorageCheck } = require("./personas");

const MEDIA_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
);

exports.register = function (shared) {
  test("seaweedfs: an uploaded WordPress media file is stored in the SeaweedFS bucket", async ({
    page,
    browser,
  }) => {
    test.skip(isOnionTarget(), "SeaweedFS is a headless backend, not a Tor surface on an onion node");
    skipUnlessServiceEnabled("seaweedfs");
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(300_000));

    await runSeaweedfsStorageCheck(page, browser, {
      label: "a WordPress media-library upload",
      action: async (appPage) => {
        await shared.wpAdminLoginViaOidc(
          appPage,
          shared.env.wpBaseUrl,
          shared.env.adminUsername,
          shared.env.adminPassword,
        );

        await appPage.goto(`${shared.env.wpBaseUrl}/wp-admin/media-new.php?browser-uploader=1`, {
          waitUntil: "domcontentloaded",
        });

        const fileInput = appPage.locator("input#async-upload, input[name='async-upload']").first();
        await expect(
          fileInput,
          "the WordPress browser uploader must expose the async-upload file input",
        ).toBeAttached({ timeout: resolveTimeout(60_000) });

        await fileInput.setInputFiles({
          name: `infinito-storage-check-${Date.now()}.png`,
          mimeType: "image/png",
          buffer: MEDIA_PNG,
        });

        await appPage
          .locator("input#html-upload, input[type='submit'][name='html-upload']")
          .first()
          .click({ timeout: resolveTimeout(60_000) });

        await expect(
          appPage.locator("body"),
          "WordPress must report the media upload, not an uploader error",
        ).not.toContainText(/unable to (create|write)|has failed to upload/i, {
          timeout: resolveTimeout(60_000),
        });
      },
    });
  });
};
