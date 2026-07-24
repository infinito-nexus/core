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

      const seed = Date.now();
      const markerBase = `infinito-storage-check-${seed}`;
      const marker = `${markerBase}.png`;
      const validPng = shared.uniqueImagePng(seed);
      const fileInput = appPage.locator("#image-upload");
      await fileInput.waitFor({ state: "attached", timeout: 60_000 });
      await fileInput.setInputFiles({ name: marker, mimeType: "image/png", buffer: validPng });

      await expect(
        appPage.getByRole("tabpanel", { name: "Layers" }).getByText(markerBase, { exact: false }).first(),
        `the uploaded image asset '${marker}' must appear as a layer in the Penpot workspace`,
      ).toBeVisible({ timeout: 60_000 });
    },
  });
});
