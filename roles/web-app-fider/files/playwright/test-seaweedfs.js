// Required env (rendered by templates/playwright.env.j2):
//   FIDER_BASE_URL, the OIDC login vars consumed by performKeycloakLoginForm,
//   and the SEAWEEDFS_* keys consumed by runSeaweedfsStorageCheck.

const { test, expect } = require("@playwright/test");
const { resolveTimeout, isOnionTarget } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { runSeaweedfsStorageCheck, performKeycloakLoginForm, decodeDotenvQuotedValue } = require("./personas");
const { clickFiderSsoButton } = require("./_shared");

const ATTACHMENT_PNG_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAMgAAADICAIAAAAiOjnJAAABeElEQVR42u3SMQ0AAAgEsVeHMDQhEBMM" +
  "DE2q4HKpHjgXCTAWxsJYYCyMhbHAWBgLY4GxMBbGAmNhLIwFxsJYGAuMhbEwFhgLY2EsMBbGwlhgLIyF" +
  "scBYGAtjgbEwFsYCY2EsjAXGwlgYC4yFsTAWGAtjYSwwFsbCWGAsjIWxwFgYC2OBsTAWxgJjYSyMBcbC" +
  "WBgLjIWxMBYYC2NhLDAWxsJYYCyMhbHAWBgLY4GxMBbGAmNhLIyFsVTAWBgLY4GxMBbGAmNhLIwFxsJY" +
  "GAuMhbEwFhgLY2EsMBbGwlhgLIyFscBYGAtjgbEwFsYCY2EsjAXGwlgYC4yFsTAWGAtjYSwwFsbCWGAs" +
  "jIWxwFgYC2OBsTAWxgJjYSyMBcbCWBgLjIWxMBYYC2NhLDAWxsJYYCyMhbHAWBgLY4GxMBbGAmNhLIyF" +
  "sVTAWBgLY4GxMBbGAmNhLIwFxsJYGAtjqYCxMBbGAmNhLIwFxsJYGAuMhbEwFhgLY2EsMBbGwlhgLIyF" +
  "scBYGAtjgbH4ZgHTqvyKw+KRzwAAAABJRU5ErkJggg==";

test.use({ ignoreHTTPSErrors: true });

test("seaweedfs: a Fider post attachment is stored in the SeaweedFS bucket", async ({ page, browser }) => {
  test.skip(isOnionTarget(), "SeaweedFS filer UI is not a Tor surface on an onion node (headless backend)");
  skipUnlessServiceEnabled("seaweedfs");
  test.setTimeout(resolveTimeout(180_000));

  const fiderBaseUrl = decodeDotenvQuotedValue(process.env.FIDER_BASE_URL || "");
  const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
  const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");
  const marker = `Storage check ${Date.now()}`;
  let post = null;

  await runSeaweedfsStorageCheck(page, browser, {
    label: "a Fider post attachment",
    action: async (appPage) => {
      expect(fiderBaseUrl, "FIDER_BASE_URL must be set for the Fider seaweedfs check").toBeTruthy();
      expect(adminUsername, "ADMIN_USERNAME must be set for the Fider seaweedfs check").toBeTruthy();
      expect(adminPassword, "ADMIN_PASSWORD must be set for the Fider seaweedfs check").toBeTruthy();

      await appPage.goto(`${fiderBaseUrl.replace(/\/$/, "")}/`, { waitUntil: "domcontentloaded" });
      await clickFiderSsoButton(appPage);
      await performKeycloakLoginForm(appPage, adminUsername, adminPassword);
      await expect(
        appPage.locator(".c-menu-user").first(),
        "the administrator must be authenticated before creating the post",
      ).toBeVisible({ timeout: resolveTimeout(60_000) });

      post = await appPage.evaluate(
        async ({ title, content }) => {
          const response = await fetch("/api/v1/posts", {
            method: "POST",
            headers: { Accept: "application/json", "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify({
              title,
              description: "A post that proves attachments reach the object store.",
              attachments: [{ upload: { fileName: "storage-check.png", contentType: "image/png", content } }],
            }),
          });
          return { status: response.status, body: await response.json().catch(() => ({})) };
        },
        { title: marker, content: ATTACHMENT_PNG_BASE64 },
      );
      expect(post.status, "Fider must accept the post with its attachment").toBe(200);
    },
  });

  const removal = await page.evaluate(async (number) => {
    const response = await fetch(`/api/v1/posts/${number}`, {
      method: "DELETE",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ text: "" }),
    });
    return response.status;
  }, post.body.number);
  expect(removal, "the storage-check post is removed again").toBe(200);
});
