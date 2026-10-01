const { test, expect } = require("@playwright/test");
const { resolveTimeout, isOnionTarget } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const {
  runSeaweedfsStorageCheck,
  performKeycloakLogin,
  clickOidcLoginLink,
  safeIsEnabled,
  decodeDotenvQuotedValue,
  normalizeBaseUrl,
  requireDotenvValue,
} = require("./personas");

const PNG_1x1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
);

const baseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(
  requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD"),
);
const adminNativePassword = decodeDotenvQuotedValue(process.env.ADMIN_NATIVE_PASSWORD || "");

test.use({ ignoreHTTPSErrors: true });

test("seaweedfs: an uploaded EspoCRM attachment is stored in the SeaweedFS bucket", async ({ page, browser }) => {
  test.skip(isOnionTarget(), "the EspoCRM admin upload surface is not driven over the node onion");
  skipUnlessServiceEnabled("seaweedfs");
  test.setTimeout(resolveTimeout(300_000));

  expect(baseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();

  const expectedBase = baseUrl.replace(/\/$/, "");
  const oidcEnabled = safeIsEnabled("sso");

  await runSeaweedfsStorageCheck(page, browser, {
    label: "an EspoCRM company-logo attachment upload",
    action: async (appPage) => {
      await appPage.context().clearCookies();
      await appPage.goto(`${expectedBase}/`, { waitUntil: "domcontentloaded" });

      if (oidcEnabled) {
        let authPage = appPage;
        if (!appPage.url().includes("openid-connect/auth")) {
          const strictLogin = appPage
            .getByRole("link", { name: /^\s*(log\s*in|sign\s*in|login|sso)\s*$/i })
            .or(appPage.getByRole("button", { name: /^\s*(log\s*in|sign\s*in|login|sso)\s*$/i }))
            .first();
          const looseLogin = appPage
            .getByRole("link", { name: /log\s*in|sign\s*in|sso/i })
            .or(appPage.getByRole("button", { name: /log\s*in|sign\s*in|sso/i }))
            .first();
          authPage = (await clickOidcLoginLink(appPage, strictLogin, looseLogin)) || appPage;
        }
        if (authPage.url().includes("openid-connect/auth")) {
          await performKeycloakLogin(authPage, adminUsername, adminPassword, canonicalDomain);
        }
      } else {
        test.skip(
          !adminNativePassword,
          "no native admin password: the role withholds it when LDAP owns authentication",
        );
        test.skip(
          safeIsEnabled("recaptcha"),
          "reCAPTCHA v3 guards the native login form with live keys a headless persona cannot satisfy",
        );
        const passwordField = appPage.locator("input[type='password']:visible").first();
        await passwordField.waitFor({ state: "visible", timeout: resolveTimeout(90_000) });
        await appPage.locator("input[name='username']:visible").first().fill(adminUsername);
        await passwordField.fill(adminNativePassword);
        await passwordField.press("Enter");
      }

      await expect
        .poll(() => appPage.url(), {
          timeout: resolveTimeout(120_000),
          message: "expected the EspoCRM login to land back on the application",
        })
        .toContain(expectedBase);

      await appPage.goto(`${expectedBase}/#Admin/userInterface`, { waitUntil: "domcontentloaded" });
      await appPage.reload({ waitUntil: "domcontentloaded" });

      const fileInput = appPage.locator('input[type="file"]').first();
      await expect(
        fileInput,
        "the EspoCRM user-interface admin page must expose the company-logo file input",
      ).toBeAttached({ timeout: resolveTimeout(120_000) });

      const attachmentCreated = appPage.waitForResponse(
        (response) =>
          /\/api\/v1\/Attachment$/.test(response.url()) && response.request().method() === "POST",
        { timeout: resolveTimeout(120_000) },
      );
      await fileInput.setInputFiles({
        name: `infinito-storage-check-${Date.now()}.png`,
        mimeType: "image/png",
        buffer: PNG_1x1,
      });
      const attachmentResponse = await attachmentCreated;
      expect(
        attachmentResponse.status(),
        "expected EspoCRM to accept the company-logo attachment",
      ).toBeLessThan(400);

      await appPage
        .getByRole("button", { name: /^(save|speichern)$/i })
        .or(appPage.locator('button[data-name="save"]'))
        .first()
        .click({ timeout: resolveTimeout(60_000) })
        .catch(() => {});
      await appPage.waitForLoadState("networkidle", { timeout: resolveTimeout(60_000) }).catch(() => {});
    },
  });
});
