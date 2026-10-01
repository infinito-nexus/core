const { test, expect } = require("@playwright/test");
const { resolveTimeout, isOnionTarget } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { runSeaweedfsStorageCheck, collectBucketObjects, seaweedfsEnv } = require("./personas");
const shared = require("./_shared");

const ATTACHMENT_BODY = Buffer.from("infinito seaweedfs storage check\n", "utf8");

test.use({ ignoreHTTPSErrors: true });

test("seaweedfs: an Odoo chatter attachment is stored in the SeaweedFS bucket", async ({ page, browser }) => {
  test.skip(isOnionTarget(), "the SeaweedFS S3 API is not a Tor surface on an onion node (headless backend)");
  skipUnlessServiceEnabled("seaweedfs");
  test.setTimeout(resolveTimeout(600_000));

  expect(shared.env.odooBaseUrl, "ODOO_BASE_URL must be set").toBeTruthy();
  expect(shared.env.adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(shared.env.adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();

  const stem = `infinito-storage-check-${Date.now()}`;

  await runSeaweedfsStorageCheck(page, browser, {
    label: "an Odoo chatter attachment upload",
    action: async (appPage) => {
      await shared.loginToOdoo(appPage);
      await shared.openModule(appPage, "odoo/contacts");

      const record = appPage.locator(".o_kanban_record:not(.o_kanban_ghost), .o_data_row").first();
      await expect(
        record,
        "the Contacts module must list at least one partner to attach a file to",
      ).toBeVisible({ timeout: resolveTimeout(120_000) });
      await record.click({ timeout: resolveTimeout(60_000) });

      const chatter = appPage.locator(".o-mail-Chatter").first();
      await expect(
        chatter,
        "the Odoo contact form must render the chatter that owns the attachment uploader",
      ).toBeVisible({ timeout: resolveTimeout(120_000) });

      const fileInput = chatter.locator('input.o-mail-Chatter-fileUploader, input[type="file"]').first();
      await expect(
        fileInput,
        "the Odoo chatter must expose its file uploader input",
      ).toBeAttached({ timeout: resolveTimeout(120_000) });

      const upload = appPage.waitForResponse(
        (response) =>
          /\/mail\/attachment\/upload/.test(response.url()) &&
          response.request().method() === "POST",
        { timeout: resolveTimeout(120_000) },
      );

      await fileInput.setInputFiles({
        name: `${stem}.txt`,
        mimeType: "text/plain",
        buffer: ATTACHMENT_BODY,
      });

      const response = await upload.catch(() => null);
      expect(
        response,
        "Odoo never POSTed the file to /mail/attachment/upload, so nothing could reach the bucket; " +
          "the chatter flow did not complete rather than the object store failing",
      ).not.toBeNull();
      expect(
        response.status(),
        `Odoo rejected the chatter attachment with HTTP ${response.status()}`,
      ).toBeLessThan(300);

      const env = seaweedfsEnv();
      const deadline = Date.now() + resolveTimeout(60_000);
      let keys = [];
      let matched = [];
      for (;;) {
        keys = [...(await collectBucketObjects(appPage.request, env)).keys()];
        matched = keys.filter((key) => key.includes(stem));
        if (matched.length > 0 || Date.now() >= deadline) {
          break;
        }
        await appPage.waitForTimeout(resolveTimeout(2_000));
      }
      expect(
        matched.length,
        `no object key in the SeaweedFS bucket '${env.bucket}' carries the uploaded file name '${stem}', ` +
          `so the chatter attachment itself did not reach the object store ` +
          `(${keys.length} key(s) present, last seen: ${keys.slice(-20).join(", ") || "none"})`,
      ).toBeGreaterThan(0);
    },
  });
});
