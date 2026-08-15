const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");

exports.register = function (shared) {
  test("administrator: every discovered MCP server is registered as a tool server", async ({ page }) => {
    skipUnlessServiceEnabled("mcp");
    test.setTimeout(120_000);

    await shared.signInViaDashboardOidc(
      page,
      shared.env.adminUsername,
      shared.env.adminPassword,
      "administrator"
    );

    const token = await page.evaluate(() => window.localStorage.getItem("token"));
    expect(
      token,
      "OpenWebUI must store a session token in localStorage after login"
    ).toBeTruthy();

    const base = shared.env.openwebuiBaseUrl.replace(/\/+$/, "");
    const response = await page.request.get(`${base}/api/v1/configs/tool_servers`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(
      response.ok(),
      `the admin tool-server config must answer the authenticated session (HTTP ${response.status()})`
    ).toBeTruthy();

    const body = await response.json();
    const connections = Array.isArray(body?.TOOL_SERVER_CONNECTIONS)
      ? body.TOOL_SERVER_CONNECTIONS
      : [];
    const mcpConnections = connections.filter((c) => c?.type === "mcp");

    const expected = (shared.env.mcpExpectedServers || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    expect(
      expected.length,
      "the deploy must have discovered at least one MCP server when the mcp service is enabled"
    ).toBeGreaterThan(0);

    const registered = mcpConnections.map((c) => String(c?.info?.id ?? ""));
    for (const id of expected) {
      expect(
        registered,
        `the administrator must see ${id} in the configured MCP tool servers (got ${JSON.stringify(registered)})`
      ).toContain(id);
    }

    for (const connection of mcpConnections) {
      expect(
        connection.auth_type,
        `${connection?.info?.id} must authenticate with a bearer token`
      ).toBe("bearer");
      expect(
        String(connection.key || "").length,
        `${connection?.info?.id} must carry a non-empty bearer, an empty one is rejected by the server`
      ).toBeGreaterThan(0);
      const grants = connection?.config?.access_grants ?? [];
      expect(
        grants,
        `${connection?.info?.id} must be scoped to its role's mcp group; an empty grant list falls back to administrator-only`
      ).toHaveLength(1);
      expect(
        grants[0],
        `${connection?.info?.id} must grant read to a group, not to a user or to everyone`
      ).toMatchObject({ principal_type: "group", permission: "read" });
      expect(
        String(grants[0]?.principal_id || ""),
        `${connection?.info?.id} must name a resolved OpenWebUI group id`
      ).not.toHaveLength(0);
      expect(
        connection?.config?.enable,
        `${connection?.info?.id} must be enabled; the deploy enables a server only together with its grant`
      ).toBeTruthy();
    }

    const tools = await page.request.get(`${base}/api/v1/tools/`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(
      tools.ok(),
      `the tool list must answer the administrator (HTTP ${tools.status()})`
    ).toBeTruthy();

    const served = JSON.stringify(await tools.json());
    for (const id of expected) {
      expect(
        served,
        `mcp is granted per application, so the administrator role alone must not serve ${id}; BYPASS_ADMIN_ACCESS_CONTROL=false is what keeps an administrator out of a grant they do not hold`
      ).not.toContain(id);
    }
  });
};
