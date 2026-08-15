const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");

exports.register = function (shared) {
  test("biber: a user outside the mcp group reaches no MCP tool", async ({ page }) => {
    skipUnlessServiceEnabled("mcp");
    test.setTimeout(120_000);

    await shared.signInViaDashboardOidc(
      page,
      shared.env.biberUsername,
      shared.env.biberPassword,
      "biber"
    );

    const token = await page.evaluate(() => window.localStorage.getItem("token"));
    expect(token, "OpenWebUI must store a session token for biber").toBeTruthy();

    const base = shared.env.openwebuiBaseUrl.replace(/\/+$/, "");
    const config = await page.request.get(`${base}/api/v1/configs/tool_servers`, {
      headers: { Authorization: `Bearer ${token}` },
      failOnStatusCode: false,
    });
    expect(
      config.status(),
      "the tool-server configuration is an administrator surface and must refuse a plain user"
    ).toBeGreaterThanOrEqual(400);

    const response = await page.request.get(`${base}/api/v1/tools/`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(response.ok(), `the tool list must answer biber (HTTP ${response.status()})`).toBeTruthy();

    const expected = (shared.env.mcpExpectedServers || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const visible = JSON.stringify(await response.json());
    for (const id of expected) {
      expect(
        visible,
        `${id} is granted to its mcp group, which biber is not in, so its tools must not be listed`
      ).not.toContain(id);
    }
  });
};
