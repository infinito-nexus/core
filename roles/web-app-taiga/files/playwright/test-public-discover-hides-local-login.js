const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { gotoOnion } = require("./personas");

exports.register = function (shared) {
  test("taiga public discover hides local login fields when oidc is active", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");

    const taigaUrls = shared.getTaigaUrls();

    await gotoOnion(page, taigaUrls.discoverUrl);
    await expect(page.getByRole("heading", { name: /discover projects/i })).toBeVisible({ timeout: resolveTimeout(60_000) });

    const authState = await shared.reachTopLevelTaigaAuthEntry(
      page,
      taigaUrls,
      60_000,
      "Expected Taiga to expose either the OIDC entry point or the Keycloak login page",
    );

    expect(authState.kind).not.toBe("taiga-local-login-visible");

    if (authState.kind === "taiga-oidc-entry") {
      await expect(authState.locator).toBeVisible({ timeout: resolveTimeout(60_000) });
      await expect
        .poll(
          async () => page.locator("input[name='username'], input#username").first().isVisible().catch(() => false),
          {
            timeout: resolveTimeout(10_000),
            message: "Expected the local Taiga username field to stay hidden when OIDC is active",
          },
        )
        .toBe(false);
      await expect
        .poll(
          async () => page.locator("input[name='password'], input#password").first().isVisible().catch(() => false),
          {
            timeout: resolveTimeout(10_000),
            message: "Expected the local Taiga password field to stay hidden when OIDC is active",
          },
        )
        .toBe(false);
      await expect
        .poll(
          async () => page.getByText(/^or login with$/i).first().isVisible().catch(() => false),
          {
            timeout: resolveTimeout(10_000),
            message: "Expected the legacy Taiga OIDC helper text to stay hidden when OIDC is active",
          },
        )
        .toBe(false);
      await expect
        .poll(
          async () => page.getByText(/^forgot it\?$/i).first().isVisible().catch(() => false),
          {
            timeout: resolveTimeout(10_000),
            message: "Expected the legacy Taiga password reset helper text to stay hidden when OIDC is active",
          },
        )
        .toBe(false);

      await authState.locator.click();
      await expect
        .poll(
          async () => page.url(),
          {
            timeout: resolveTimeout(60_000),
            message: `Expected the Taiga OIDC entry to navigate to Keycloak: ${taigaUrls.expectedOidcAuthUrl}`,
          },
        )
        .toContain(taigaUrls.expectedOidcAuthUrl);
    }

    await expect(page.locator("input[name='username'], input#username").first()).toBeVisible({ timeout: resolveTimeout(60_000) });
  });
};
