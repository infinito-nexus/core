const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("biber (customer): creates a ticket via the SPA after OIDC login", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    expect(shared.env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
    expect(shared.env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();

    await shared.signInViaZammadOidc(page, shared.env.biberUsername, shared.env.biberPassword, "biber");

    const subject = `playwright-customer-${Date.now()}`;

    await page
      .goto(`${shared.env.zammadBaseUrl}/#customer_ticket_new`, { waitUntil: "domcontentloaded" })
      .catch(() => {});

    const titleField = page
      .getByRole("textbox", { name: /title|subject|betreff/i })
      .or(page.locator("input[name='title'], input[id*='title']"))
      .first();
    await titleField.waitFor({ state: "visible", timeout: 60_000 });
    await titleField.fill(subject);

    const bodyField = page
      .getByRole("textbox", { name: /body|message|text|nachricht|description/i })
      .or(page.locator("div[contenteditable='true'], textarea"))
      .first();
    await bodyField.waitFor({ state: "visible", timeout: 30_000 });
    await bodyField.fill("Ticket from the Infinito.Nexus customer-persona Playwright suite.");

    const submitButton = page
      .getByRole("button", { name: /create|submit|send|absenden|erstellen/i })
      .first();
    await submitButton.click();

    await expect(page.locator("body")).toContainText(subject, { timeout: 60_000 });

    await shared.zammadLogout(page);
  });
};
