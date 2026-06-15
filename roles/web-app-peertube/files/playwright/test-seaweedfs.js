const path = require("path");
const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const {
  runSeaweedfsStorageCheck,
  performKeycloakLoginForm,
  decodeDotenvQuotedValue,
  normalizeBaseUrl,
} = require("./personas");

test.use({ ignoreHTTPSErrors: true });

const peertubeBaseUrl = normalizeBaseUrl(process.env.PEERTUBE_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const oidcButtonText = decodeDotenvQuotedValue(process.env.OIDC_BUTTON_TEXT || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");

async function loginAdminViaOidc(page) {
  const expectedOidcAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;

  await page.goto(`${peertubeBaseUrl}/login`, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle").catch(() => {});

  const oidcButtonPatterns = [
    oidcButtonText ? new RegExp(oidcButtonText.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i") : null,
    /open\s*id\s*connect/i,
    /single\s+sign[-\s]*on/i,
    /continue\s+with\s+oidc/i,
    /sign\s*in\s+with\s+oidc/i,
  ].filter(Boolean);

  await expect
    .poll(
      async () => {
        if (page.url().includes(expectedOidcAuthUrl)) return true;
        for (const pattern of oidcButtonPatterns) {
          const candidate = page.locator("a, button").filter({ hasText: pattern }).first();
          if ((await candidate.count().catch(() => 0)) > 0) {
            await candidate.waitFor({ state: "visible", timeout: 30_000 }).catch(() => {});
            await candidate.click().catch(() => {});
            break;
          }
        }
        return page.url().includes(expectedOidcAuthUrl);
      },
      {
        timeout: 60_000,
        message: `expected redirect to Keycloak OIDC auth (${expectedOidcAuthUrl})`,
      }
    )
    .toBe(true);

  await performKeycloakLoginForm(page, adminUsername, adminPassword);

  await expect
    .poll(() => page.url(), {
      timeout: 60_000,
      message: `expected redirect back to PeerTube at ${peertubeBaseUrl}`,
    })
    .toContain(peertubeBaseUrl);

  const authenticatedMarker = page
    .locator("my-avatar-menu, my-user-notifications, my-header my-avatar, a[href='/my-account'], button.dropdown-toggle my-avatar")
    .first();
  await expect(authenticatedMarker, "expected an authenticated PeerTube UI marker after OIDC login").toBeVisible({
    timeout: 60_000,
  });
}

async function uploadWebVideo(page) {
  await page.goto(`${peertubeBaseUrl}/videos/upload`, { waitUntil: "domcontentloaded" });

  const marker = `infinito-storage-check-${Date.now()}`;

  const fileInput = page.locator("input[type='file']").first();
  await fileInput.waitFor({ state: "attached", timeout: 60_000 });
  await fileInput.setInputFiles(path.join(__dirname, "fixtures", "video_short.mp4"));

  const nameField = page
    .getByLabel(/name/i)
    .or(page.locator("input#name, input[formcontrolname='name'], input[name='name']"))
    .first();
  await nameField.waitFor({ state: "visible", timeout: 60_000 });
  await nameField.fill(marker);

  const welcomeDialog = page.locator("ngb-modal-window, .modal.show, [role='dialog']").first();
  if (await welcomeDialog.isVisible().catch(() => false)) {
    const closeBtn = welcomeDialog
      .getByRole("button", { name: /close|got it|continue|skip|i'?m a/i })
      .or(welcomeDialog.locator("button.close, [aria-label='Close']"))
      .first();
    if (await closeBtn.isVisible().catch(() => false)) {
      await closeBtn.click().catch(() => {});
    } else {
      await page.keyboard.press("Escape").catch(() => {});
    }
    await welcomeDialog.waitFor({ state: "hidden", timeout: 15_000 }).catch(() => {});
  }

  const publishButton = page.locator(".save-button > button").first();
  await publishButton.waitFor({ state: "visible", timeout: 60_000 });
  await expect(
    publishButton,
    "expected the PeerTube publish button to become enabled after the upload finishes",
  ).toBeEnabled({ timeout: 120_000 });

  await publishButton.click();

  const savedMarker = page
    .locator(".save-button > button[disabled]")
    .or(page.locator("my-video-watch, .video-info-name, h1.video-info-name"))
    .or(page.getByText(marker, { exact: false }))
    .first();
  await expect(
    savedMarker,
    `the uploaded video '${marker}' must be saved by PeerTube before the S3 move job runs`,
  ).toBeVisible({ timeout: 120_000 });
}

test("seaweedfs: an uploaded PeerTube video is stored in the SeaweedFS bucket", async ({ page, browser }) => {
  skipUnlessServiceEnabled("seaweedfs");
  test.setTimeout(480_000);

  await runSeaweedfsStorageCheck(page, browser, {
    label: "a PeerTube video upload",
    pollDeadlineMs: 300_000,
    action: async (appPage) => {
      await loginAdminViaOidc(appPage);
      await uploadWebVideo(appPage);
    },
  });
});
