const { test, expect, request } = require("@playwright/test");

async function seedTicketViaApi(baseUrl, adminUsername, adminPassword, subject) {
  const api = await request.newContext({
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: {
      Authorization: `Basic ${  Buffer.from(`${adminUsername}:${adminPassword}`).toString("base64")}`,
      "Content-Type": "application/json",
    },
  });

  const resp = await api.post(`${baseUrl}/api/v1/tickets`, {
    data: {
      title: subject,
      group: "Users",
      customer: adminUsername,
      article: {
        subject,
        body: "Seed article for the agent-reply Playwright scenario.",
        type: "note",
        internal: false,
      },
    },
  });

  if (resp.status() >= 300) {
    throw new Error(`Seed POST /api/v1/tickets failed: ${resp.status()} ${await resp.text()}`);
  }
  const ticket = await resp.json();
  await api.dispose();
  return ticket;
}

exports.register = function (shared) {
  test("administrator (agent): replies to an API-seeded ticket via the SPA", async ({ page }) => {
    shared.skipUnlessServiceEnabled("oidc");
    expect(shared.env.adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
    expect(shared.env.adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();

    const subject = `playwright-agent-reply-${Date.now()}`;
    const ticket = await seedTicketViaApi(
      shared.env.zammadBaseUrl,
      shared.env.adminUsername,
      shared.env.adminPassword,
      subject
    );

    await shared.signInViaZammadOidc(page, shared.env.adminUsername, shared.env.adminPassword, "administrator");

    await page.goto(`${shared.env.zammadBaseUrl}/#ticket/zoom/${ticket.id}`, { waitUntil: "domcontentloaded" });
    await expect(page.locator("body")).toContainText(subject, { timeout: 60_000 });

    const replyBody = page
      .locator("div[contenteditable='true']")
      .or(page.locator("textarea[name='body']"))
      .first();
    await replyBody.waitFor({ state: "visible", timeout: 60_000 });

    const replyText = `agent-reply ${Date.now()}`;
    await replyBody.click();
    await page.keyboard.type(replyText);

    const updateButton = page
      .getByRole("button", { name: /update|aktualisieren/i })
      .first();
    await updateButton.click();

    await expect(page.locator("body")).toContainText(replyText, { timeout: 60_000 });

    await shared.zammadLogout(page);
  });
};
