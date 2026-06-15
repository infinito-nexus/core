const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { runSeaweedfsStorageCheck } = require("./personas");
const shared = require("./_shared");

// A real >1px PNG: Taiga's change_avatar runs pil_image() which rejects the
// degenerate 1x1 sample ("Truncated File Read") before any S3 write happens.
const AVATAR_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAMgAAADICAIAAAAiOjnJAAABeElEQVR42u3SMQ0AAAgEsVeHMDQhEBMM" +
    "DE2q4HKpHjgXCTAWxsJYYCyMhbHAWBgLY4GxMBbGAmNhLIwFxsJYGAuMhbEwFhgLY2EsMBbGwlhgLIyF" +
    "scBYGAtjgbEwFsYCY2EsjAXGwlgYC4yFsTAWGAtjYSwwFsbCWGAsjIWxwFgYC2OBsTAWxgJjYSyMBcbC" +
    "WBgLjIWxMBYYC2NhLDAWxsJYYCyMhbHAWBgLY4GxMBbGAmNhLIyFsVTAWBgLY4GxMBbGAmNhLIwFxsJY" +
    "GAuMhbEwFhgLY2EsMBbGwlhgLIyFscBYGAtjgbEwFsYCY2EsjAXGwlgYC4yFsTAWGAtjYSwwFsbCWGAs" +
    "jIWxwFgYC2OBsTAWxgJjYSyMBcbCWBgLjIWxMBYYC2NhLDAWxsJYYCyMhbHAWBgLY4GxMBbGAmNhLIyF" +
    "sVTAWBgLY4GxMBbGAmNhLIwFxsJYGAtjqYCxMBbGAmNhLIwFxsJYGAuMhbEwFhgLY2EsMBbGwlhgLIyF" +
    "scBYGAtjgbH4ZgHTqvyKw+KRzwAAAABJRU5ErkJggg==",
  "base64",
);

test.use({ ignoreHTTPSErrors: true });

test("seaweedfs: an uploaded Taiga avatar is stored in the SeaweedFS bucket", async ({ page, browser }) => {
  skipUnlessServiceEnabled("seaweedfs");
  test.setTimeout(180_000);

  await runSeaweedfsStorageCheck(page, browser, {
    label: "a Taiga user avatar upload",
    action: async (appPage) => {
      const taigaUrls = await shared.loginToTaiga(appPage);

      await appPage.goto(taigaUrls.userSettingsUrl, { waitUntil: "domcontentloaded" });

      const fileInput = appPage.locator('input[type="file"]').first();
      await expect(
        fileInput,
        "the Taiga user-profile page must expose a file input to change the avatar photo",
      ).toBeAttached({ timeout: 60_000 });

      const marker = `infinito-storage-check-${Date.now()}.png`;
      await fileInput.setInputFiles({
        name: marker,
        mimeType: "image/png",
        buffer: AVATAR_PNG,
      });

      const saveAction = appPage
        .getByRole("button", { name: /save|upload|change/i })
        .or(appPage.locator('button[type="submit"], a.button-save, .save'))
        .first();
      if (await saveAction.isVisible({ timeout: 10_000 }).catch(() => false)) {
        await saveAction.click().catch(() => {});
      }

      const rejection = appPage.getByText(/invalid image format|something went wrong/i).first();
      if (await rejection.isVisible({ timeout: 15_000 }).catch(() => false)) {
        throw new Error("Taiga rejected the avatar upload (change_avatar pil_image validation) — no object written to SeaweedFS");
      }
    },
  });
});
