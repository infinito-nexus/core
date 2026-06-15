// SeaweedFS object-store scenario for Pixelfed.
//
// Pixelfed is configured with the S3 cloud filesystem (env.j2:
// PF_ENABLE_CLOUD=true, FILESYSTEM_DRIVER=s3, FILESYSTEM_CLOUD=s3, AWS_BUCKET),
// so media a user uploads through the compose flow is flushed to the consumer
// bucket instead of the local disk. The action logs the administrator in and
// publishes a tiny PNG through the new-post composer; the shared check proves
// the bucket grew via the Filer UI.
//
// IMPORTANT: Pixelfed's web composer (ComposeModal.vue, route /i/web/compose)
// does NOT upload media when the hidden #pf-dz file input changes — onInputFile
// only buffers the file client-side and advances the wizard to its caption
// step. The POST to /api/compose/v0/media/upload (the actual S3 write) and the
// subsequent /api/compose/v0/publish only fire when the "Post" action runs
// compose(). So selecting the file is not enough; the test must click "Post"
// and wait for the post redirect, otherwise no object ever reaches the bucket.
//
// Required env (rendered by templates/playwright.env.j2):
//   PIXELFED_BASE_URL, the login vars consumed by loginToPixelfed, and the
//   SEAWEEDFS_* keys consumed by runSeaweedfsStorageCheck.

const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { runSeaweedfsStorageCheck } = require("./personas");
const shared = require("./_shared");

const PNG_1x1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
);

function pixelfedAdminScenario() {
  const scenarios = shared.loginScenarios || [];
  return scenarios.find((scenario) => scenario.label === "administrator") || scenarios[0];
}

test.use({ ignoreHTTPSErrors: true });

test("seaweedfs: an uploaded Pixelfed photo is stored in the SeaweedFS bucket", async ({ page, browser }) => {
  skipUnlessServiceEnabled("seaweedfs");
  test.setTimeout(180_000);

  await runSeaweedfsStorageCheck(page, browser, {
    label: "a Pixelfed composer photo upload",
    action: async (appPage) => {
      const scenario = pixelfedAdminScenario();
      expect(scenario, "a login scenario must be configured for the Pixelfed seaweedfs check").toBeTruthy();

      await shared.loginToPixelfed(appPage, scenario);

      const baseUrl = shared.env.pixelfedBaseUrl.replace(/\/$/, "");
      await appPage.goto(`${baseUrl}/i/web/compose`, { waitUntil: "domcontentloaded" });

      const fileInput = appPage.locator('input#pf-dz, input[type="file"][name="media"], input[type="file"]').first();
      await expect(
        fileInput,
        "the Pixelfed composer must expose a file input to attach a photo",
      ).toBeAttached({ timeout: 60_000 });

      const marker = `infinito-storage-check-${Date.now()}.png`;
      await fileInput.setInputFiles({
        name: marker,
        mimeType: "image/png",
        buffer: PNG_1x1,
      });

      const postAction = appPage
        .getByRole("link", { name: /^Post$/i })
        .or(appPage.getByRole("button", { name: /^Post$/i }))
        .first();
      await expect(
        postAction,
        "the Pixelfed composer must advance to its caption step and expose a Post action after a photo is attached",
      ).toBeVisible({ timeout: 60_000 });
      await postAction.click();

      await expect
        .poll(() => appPage.url(), {
          timeout: 90_000,
          message:
            "Pixelfed must publish the composed photo (media upload to S3 + /api/compose/v0/publish), then redirect away from /i/web/compose to the new post",
        })
        .not.toContain("/i/web/compose");
    },
  });
});
