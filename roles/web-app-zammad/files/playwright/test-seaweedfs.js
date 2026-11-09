// SeaweedFS object-store scenario for Zammad.
//
// Required env (rendered by templates/playwright.env.j2):
//   ZAMMAD_BASE_URL, ADMIN_API_USERNAME, ADMIN_API_PASSWORD and the SEAWEEDFS_*
//   keys consumed by runSeaweedfsStorageCheck.

const { randomUUID } = require("node:crypto");
const { test, expect } = require("@playwright/test");
const { resolveTimeout, isOnionTarget } = require("./timeouts");
const { gotoOnion, runSeaweedfsStorageCheck } = require("./personas");

exports.register = function (shared) {
  test("seaweedfs: a Zammad ticket attachment is stored in the SeaweedFS bucket", async ({ page, browser }) => {
    test.skip(isOnionTarget(), "the SeaweedFS S3 API is not a Tor surface on an onion node (headless backend)");
    shared.skipUnlessServiceEnabled("seaweedfs");
    expect(shared.env.adminApiUsername, "ADMIN_API_USERNAME must be set").toBeTruthy();
    expect(shared.env.adminApiPassword, "ADMIN_API_PASSWORD must be set").toBeTruthy();
    test.setTimeout(resolveTimeout(300_000));

    await runSeaweedfsStorageCheck(page, browser, {
      label: "a Zammad ticket attachment upload",
      action: async (appPage) => {
        const subject = `playwright-seaweedfs-${Date.now()}`;
        const ticket = await shared.seedTicketViaApi(
          subject,
          "Seed article for the SeaweedFS storage-check scenario."
        );

        await shared.signInAsApiBot(appPage);
        await gotoOnion(appPage, `${shared.env.zammadBaseUrl}/#ticket/zoom/${ticket.id}`, { waitUntil: "domcontentloaded" });
        await expect(appPage.locator("body")).toContainText(subject, { timeout: resolveTimeout(60_000) });

        await appPage
          .locator('.article-add [contenteditable="true"]')
          .first()
          .waitFor({ state: "visible", timeout: resolveTimeout(60_000) });

        const fileInput = appPage
          .locator('.article-add input[type="file"]')
          .or(appPage.locator('input[type="file"]'))
          .first();
        await expect(
          fileInput,
          "the Zammad ticket zoom must expose a file input to attach a file to the reply",
        ).toBeAttached({ timeout: resolveTimeout(60_000) });

        const upload = appPage.waitForResponse(
          (response) =>
            /\/api\/v1\/upload_caches\//.test(response.url()) &&
            response.request().method() === "POST",
          { timeout: resolveTimeout(120_000) },
        );

        const marker = `infinito-storage-check-${Date.now()}-${randomUUID()}`;
        await fileInput.setInputFiles({
          name: `${marker}.txt`,
          mimeType: "text/plain",
          buffer: Buffer.from(`Infinito.Nexus SeaweedFS storage check ${marker}\n`, "utf8"),
        });

        const response = await upload.catch(() => null);
        expect(
          response,
          "Zammad never POSTed the attachment to POST /api/v1/upload_caches/:form_id, so nothing could reach " +
            "the bucket; the ticket-zoom reply form did not accept the file rather than the object store failing",
        ).not.toBeNull();
        expect(
          response.status(),
          `Zammad rejected the attachment upload with HTTP ${response.status()}`,
        ).toBeLessThan(300);
      },
    });
  });
};
