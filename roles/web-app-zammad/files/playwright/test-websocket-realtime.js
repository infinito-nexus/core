const { test, expect, request } = require("@playwright/test");

async function seedTicketViaApi(baseUrl, adminApiUsername, adminApiPassword, subject) {
  const api = await request.newContext({
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: {
      Authorization: `Basic ${Buffer.from(`${adminApiUsername}:${adminApiPassword}`).toString("base64")}`,
      "Content-Type": "application/json",
    },
  });
  const resp = await api.post(`${baseUrl}/api/v1/tickets`, {
    data: {
      title: subject,
      group: "Users",
      customer: adminApiUsername,
      article: { subject, body: "Seed.", type: "note", internal: false },
    },
  });
  if (resp.status() >= 300) {
    throw new Error(`Seed POST /api/v1/tickets failed: ${resp.status()} ${await resp.text()}`);
  }
  const ticket = await resp.json();
  await api.dispose();
  return ticket;
}

async function appendArticleViaApi(baseUrl, adminApiUsername, adminApiPassword, ticketId, body) {
  const api = await request.newContext({
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: {
      Authorization: `Basic ${Buffer.from(`${adminApiUsername}:${adminApiPassword}`).toString("base64")}`,
      "Content-Type": "application/json",
    },
  });
  const resp = await api.post(`${baseUrl}/api/v1/ticket_articles`, {
    data: { ticket_id: ticketId, subject: "ws-update", body, type: "note", internal: false },
  });
  await api.dispose();
  if (resp.status() >= 300) {
    throw new Error(`Append article failed: ${resp.status()}`);
  }
}

exports.register = function (shared) {
  test("administrator: zammad-websocket pushes ticket updates to an open session in real time", async ({ page }) => {
    expect(shared.env.adminApiUsername, "ADMIN_API_USERNAME must be set").toBeTruthy();
    expect(shared.env.adminApiPassword, "ADMIN_API_PASSWORD must be set").toBeTruthy();

    const subject = `playwright-ws-${Date.now()}`;
    const ticket = await seedTicketViaApi(
      shared.env.zammadBaseUrl,
      shared.env.adminApiUsername,
      shared.env.adminApiPassword,
      subject
    );

    await shared.signInAsApiBot(page);
    await page.goto(`${shared.env.zammadBaseUrl}/#ticket/zoom/${ticket.id}`, { waitUntil: "domcontentloaded" });
    await expect(page.locator("body")).toContainText(subject, { timeout: 60_000 });

    const wsMarker = `ws-realtime-${Date.now()}`;
    await appendArticleViaApi(
      shared.env.zammadBaseUrl,
      shared.env.adminApiUsername,
      shared.env.adminApiPassword,
      ticket.id,
      wsMarker
    );

    await expect(page.locator("body")).toContainText(wsMarker, { timeout: 60_000 });

    await shared.zammadLogout(page);
  });
};
