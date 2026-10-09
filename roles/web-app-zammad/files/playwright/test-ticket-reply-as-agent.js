const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { gotoOnion } = require("./personas");

exports.register = function (shared) {
  test("administrator (agent): replies to an API-seeded ticket via the SPA", async ({ page }) => {
    expect(shared.env.adminApiUsername, "ADMIN_API_USERNAME must be set").toBeTruthy();
    expect(shared.env.adminApiPassword, "ADMIN_API_PASSWORD must be set").toBeTruthy();

    const subject = `playwright-agent-reply-${Date.now()}`;
    const ticket = await shared.seedTicketViaApi(
      subject,
      "Seed article for the agent-reply Playwright scenario."
    );

    await shared.signInAsApiBot(page);
    await gotoOnion(page, `${shared.env.zammadBaseUrl}/#ticket/zoom/${ticket.id}`, { waitUntil: "domcontentloaded" });
    await expect(page.locator("body")).toContainText(subject, { timeout: resolveTimeout(60_000) });

    // Clue-tooltip close handler races the backdrop animation and re-opens; nuke the DOM nodes.
    await page.evaluate(() => {
      document.querySelectorAll('.js-modal--clue, .modal-backdrop').forEach((el) => el.remove());
    });

    const replyText = `agent-reply ${Date.now()}`;
    const replyBody = page.locator('.article-add [contenteditable="true"]').first();
    await replyBody.waitFor({ state: "visible", timeout: resolveTimeout(60_000) });
    await replyBody.evaluate((el, text) => {
      el.focus();
      el.innerText = text;
      el.dispatchEvent(new InputEvent("input", { bubbles: true, data: text }));
    }, replyText);

    const updateButton = page
      .locator('button.js-submit, button[data-name="submit"]')
      .or(page.getByRole("button", { name: /^(update|aktualisieren)$/i }))
      .first();
    await updateButton.waitFor({ state: "visible", timeout: resolveTimeout(60_000) });
    await updateButton.click();

    await expect(page.locator("body")).toContainText(replyText, { timeout: resolveTimeout(60_000) });

    await shared.zammadLogout(page);
  });
};
