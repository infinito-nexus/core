// SeaweedFS object-store scenario for Mattermost.
//
// Mattermost is configured with S3 file storage
// (MM_FILESETTINGS_DRIVERNAME=amazons3, MM_FILESETTINGS_AMAZONS3BUCKET), so a
// file attached to a channel message is written to the consumer bucket. The
// action signs the administrator in over OIDC, opens a channel, attaches a
// file to a post and submits it; the shared check proves the bucket grew via
// the Filer UI.
//
// Mattermost trims displayed filenames to the first 35 chars + "..."
// (utils trimFilename / MAX_FILENAME_LENGTH = 35), so the full 40-char marker
// never appears in a single text node. The visibility assertions therefore
// match a stable 30-char prefix that survives the truncation in both the
// draft preview and the posted attachment overlay.

const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { runSeaweedfsStorageCheck } = require("./personas");
const { performKeycloakLoginForm } = require("./personas");
const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

test("seaweedfs: a Mattermost message attachment is stored in the SeaweedFS bucket", async ({ page, browser }) => {
  skipUnlessServiceEnabled("seaweedfs");
  test.setTimeout(180_000);

  await runSeaweedfsStorageCheck(page, browser, {
    label: "a Mattermost message attachment upload",
    action: async (appPage) => {
      const baseUrl = shared.expectedMattermostBaseUrl();

      await shared.startMattermostSsoFlow(appPage, baseUrl);
      await expect
        .poll(() => appPage.url(), {
          timeout: 30_000,
          message: `Expected redirect to Keycloak OIDC: ${shared.expectedOidcAuthUrl()}`,
        })
        .toContain(shared.expectedOidcAuthUrl());

      await performKeycloakLoginForm(appPage, shared.env.adminUsername, shared.env.adminPassword);

      await expect
        .poll(() => appPage.url(), {
          timeout: 60_000,
          message: "Expected redirect back to Mattermost after admin login",
        })
        .toContain(baseUrl);

      await shared.dismissMattermostPopups(appPage);

      await appPage.goto(`${baseUrl}/main/channels/town-square`, { waitUntil: "domcontentloaded" });
      await shared.dismissMattermostPopups(appPage);
      await shared.waitForMattermostChannelView(appPage, 60_000);

      const messageInput = appPage
        .locator("#post_textbox, [data-testid='post_textbox'], div[contenteditable='true'].post-create__input")
        .first();
      await messageInput.waitFor({ state: "visible", timeout: 30_000 });

      const marker = `infinito-storage-check-${Date.now()}.txt`;
      const markerPrefix = marker.slice(0, 30);
      const fileInput = appPage
        .locator("input[type='file'][data-testid='fileUploadInput'], .file-input, input[type='file']")
        .first();
      await fileInput.waitFor({ state: "attached", timeout: 30_000 });
      await fileInput.setInputFiles({
        name: marker,
        mimeType: "text/plain",
        buffer: Buffer.from(`infinito storage check ${marker}`),
      });

      const attachmentPreview = appPage
        .getByText(markerPrefix, { exact: false })
        .or(appPage.locator(".file-preview, [data-testid='fileAttachment'], .post-image__thumbnail"))
        .first();
      await expect(
        attachmentPreview,
        `the attachment '${marker}' must appear in the post preview before sending`,
      ).toBeVisible({ timeout: 30_000 });

      await messageInput.click({ force: true });
      await appPage.keyboard.type(`storage check ${marker}`);
      await appPage.keyboard.press("Enter");

      await expect(
        appPage.getByTestId("postContent").getByText(markerPrefix, { exact: false }).first(),
        `the sent attachment '${marker}' must appear in the channel timeline`,
      ).toBeVisible({ timeout: 30_000 });
    },
  });
});
