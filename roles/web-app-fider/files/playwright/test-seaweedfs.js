// SeaweedFS object-store scenario for Fider.
//
// Fider is configured with the S3 blob backend (env.j2: BLOB_STORAGE=s3 +
// BLOB_STORAGE_S3_BUCKET / _ACCESS_KEY_ID / _SECRET_ACCESS_KEY /
// _ENDPOINT_URL / _REGION), so a tenant logo the administrator uploads on the
// admin General settings page is written to the consumer bucket as a new
// private blob (Fider stores blobs with ACL=private and reverse-proxies them
// through its own /images route, which is why the role declares no public
// flag). The action signs the administrator in through Fider's SSO button +
// Keycloak form, opens the admin General settings page, sets the "Your Logo"
// file input to a small PNG and clicks Save; the shared check proves the
// bucket grew via the Filer UI.
//
// Required env (rendered by templates/playwright.env.j2):
//   FIDER_BASE_URL, the OIDC login vars consumed by performKeycloakLoginForm,
//   and the SEAWEEDFS_* keys consumed by runSeaweedfsStorageCheck.

const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { runSeaweedfsStorageCheck, performKeycloakLoginForm, decodeDotenvQuotedValue } = require("./personas");

const LOGO_PNG = Buffer.from(
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

async function clickFiderSsoButton(locator) {
  const signInLink = locator.getByRole("link", { name: /sign in/i });
  await signInLink.first().waitFor({ state: "visible", timeout: 30_000 });
  await signInLink.first().click();

  const ssoButton = locator.getByRole("link", { name: /continue with/i });
  await ssoButton.first().waitFor({ state: "visible", timeout: 15_000 });
  await ssoButton.first().click({ force: true });
}

test.use({ ignoreHTTPSErrors: true });

test("seaweedfs: an uploaded Fider tenant logo is stored in the SeaweedFS bucket", async ({ page, browser }) => {
  skipUnlessServiceEnabled("seaweedfs");
  test.setTimeout(180_000);

  const fiderBaseUrl = decodeDotenvQuotedValue(process.env.FIDER_BASE_URL || "");
  const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
  const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");

  await runSeaweedfsStorageCheck(page, browser, {
    label: "a Fider admin tenant-logo upload",
    expectInPlaceOverwrite: true,
    action: async (appPage) => {
      expect(fiderBaseUrl, "FIDER_BASE_URL must be set for the Fider seaweedfs check").toBeTruthy();
      expect(adminUsername, "ADMIN_USERNAME must be set for the Fider seaweedfs check").toBeTruthy();
      expect(adminPassword, "ADMIN_PASSWORD must be set for the Fider seaweedfs check").toBeTruthy();

      const baseUrl = fiderBaseUrl.replace(/\/$/, "");

      await appPage.goto(`${baseUrl}/`, { waitUntil: "domcontentloaded" });
      await clickFiderSsoButton(appPage);
      await performKeycloakLoginForm(appPage, adminUsername, adminPassword);

      await expect(
        appPage.locator(".c-menu-user").first(),
        "the administrator must be authenticated before opening the admin settings",
      ).toBeVisible({ timeout: 60_000 });

      await appPage.goto(`${baseUrl}/admin`, { waitUntil: "domcontentloaded" });

      const fileInput = appPage.locator('input[type="file"][accept="image/*"]').first();
      await expect(
        fileInput,
        "the Fider admin General settings page must expose the 'Your Logo' image input",
      ).toBeAttached({ timeout: 60_000 });

      const marker = `infinito-storage-check-${Date.now()}.png`;
      await fileInput.setInputFiles({
        name: marker,
        mimeType: "image/png",
        buffer: LOGO_PNG,
      });

      await expect(
        appPage.locator('.c-image-upload img[src^="data:image"], .preview img[src^="data:image"]').first(),
        "the selected logo must be loaded into the form (preview rendered) before saving",
      ).toBeVisible({ timeout: 30_000 });

      const saveButton = appPage.getByRole("button", { name: /^save$/i }).first();
      await expect(
        saveButton,
        "the Fider admin General settings page must expose a Save action that persists the logo",
      ).toBeVisible({ timeout: 60_000 });
      const [settingsResp] = await Promise.all([
        appPage.waitForResponse(
          (r) => /\/_api\/admin\/settings\/general/.test(r.url()) && r.request().method() === "POST",
          { timeout: 60_000 },
        ),
        saveButton.click(),
      ]);
      expect(
        settingsResp.ok(),
        `Fider must accept the General-settings save that persists the logo (got HTTP ${settingsResp.status()})`,
      ).toBeTruthy();
      const reqBody = settingsResp.request().postData() || "";
      expect(
        reqBody,
        "the General-settings save must carry the logo upload payload (empty upload = silent no-op)",
      ).toMatch(/"upload"\s*:\s*\{[^}]*"content"/);
    },
  });
});
