const { test, expect, request } = require("@playwright/test");

exports.register = function (shared) {
  test("administrator: REST API POST /api/v1/tickets creates a ticket", async () => {
    expect(shared.env.adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
    expect(shared.env.adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();

    const api = await request.newContext({
      ignoreHTTPSErrors: true,
      extraHTTPHeaders: {
        Authorization:
          `Basic ${ 
          Buffer.from(`${shared.env.adminUsername}:${shared.env.adminPassword}`).toString("base64")}`,
        "Content-Type": "application/json",
      },
    });

    const subject = `playwright-rest-${Date.now()}`;

    const createResp = await api.post(`${shared.env.zammadBaseUrl}/api/v1/tickets`, {
      data: {
        title: subject,
        group: "Users",
        customer: shared.env.adminUsername,
        article: {
          subject,
          body: "Created from the Infinito.Nexus Playwright REST regression suite.",
          type: "note",
          internal: false,
        },
      },
    });

    expect(
      createResp.status(),
      `POST /api/v1/tickets unexpected status: ${await createResp.text()}`
    ).toBeLessThan(300);

    const created = await createResp.json();
    expect(created.id, "created ticket must carry an id").toBeTruthy();
    expect(created.title, "created ticket title must round-trip").toBe(subject);

    const getResp = await api.get(`${shared.env.zammadBaseUrl}/api/v1/tickets/${created.id}`);
    expect(getResp.status(), "Created ticket must be GETtable").toBeLessThan(300);

    await api.dispose();
  });
};
