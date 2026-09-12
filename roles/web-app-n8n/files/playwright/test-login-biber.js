const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("biber: the proxy refuses a persona holding none of the admitted groups", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    expect(shared.env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
    expect(shared.env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();
    expect(shared.env.oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();

    await shared.signInViaN8nOidc(page, shared.env.biberUsername, shared.env.biberPassword, "biber");

    await expect(page.locator("body"), {
      message:
        "biber reached n8n's authenticated surface; meta/services.yml admits only the administrator and mcp groups and biber holds neither, so the gate is open to a persona that carries no role",
    }).not.toContainText(/workflow|execution|credential|canvas|overview/i, {
      timeout: resolveTimeout(60_000),
    });

    await expect(page.locator("body"), {
      message:
        "the page is neither n8n's surface nor a recognisable denial; the proxy may have changed its rejection wording",
    }).toContainText(/403|forbidden|permission|unauthorized|access denied/i);
  });
};
