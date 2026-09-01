const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");

exports.register = function (shared) {
  test("administrator: every registered MCP server answers Open WebUI's client", async ({
    page,
  }) => {
    skipUnlessServiceEnabled("mcp");

    const expected = (shared.env.mcpExpectedServers || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    expect(
      expected.length,
      "the deploy must have discovered at least one MCP server when the mcp service is enabled"
    ).toBeGreaterThan(0);

    test.setTimeout(resolveTimeout(60_000 + expected.length * 20_000));

    await shared.signInViaDashboardOidc(
      page,
      shared.env.adminUsername,
      shared.env.adminPassword,
      "administrator"
    );

    const token = await page.evaluate(() => window.localStorage.getItem("token"));
    expect(token, "OpenWebUI must store a session token after login").toBeTruthy();
    const headers = { Authorization: `Bearer ${token}` };
    const base = shared.env.openwebuiBaseUrl.replace(/\/+$/, "");

    const readProbes = JSON.parse(shared.env.mcpExpectedTools || "{}");

    const config = await page.request.get(`${base}/api/v1/configs/tool_servers`, {
      headers,
    });
    expect(
      config.ok(),
      `the admin tool-server config must answer the authenticated session (HTTP ${config.status()})`
    ).toBeTruthy();
    const connections = (await config.json())?.TOOL_SERVER_CONNECTIONS ?? [];

    const verifiable = expected.filter((id) => {
      const connection = connections.find(
        (c) => c?.type === "mcp" && String(c?.info?.id ?? "") === id
      );
      expect(connection, `${id} must be a configured MCP tool server`).toBeTruthy();
      return connection.auth_type === "bearer";
    });
    expect(
      verifiable.length,
      `none of ${JSON.stringify(expected)} authenticates with a deployment bearer; only a bearer connection carries its credential in the row, a system_oauth one resolves the caller's own upstream token and the administrator holds none, so there is nothing here this spec can verify against the bridge`
    ).toBeGreaterThan(0);

    for (const id of verifiable) {
      const connection = connections.find(
        (c) => c?.type === "mcp" && String(c?.info?.id ?? "") === id
      );

      const verify = await page.request.post(
        `${base}/api/v1/configs/tool_servers/verify`,
        { headers, data: connection }
      );
      expect(
        verify.ok(),
        `${id} did not answer Open WebUI's MCP client (HTTP ${verify.status()}); the endpoint is down, the deployed bearer is refused, or the transport disagrees`
      ).toBeTruthy();

      const specs = (await verify.json())?.specs ?? [];
      expect(
        specs.length,
        `${id} completed the handshake but served no tool; a client would be configured against an empty surface`
      ).toBeGreaterThan(0);

      const probe = readProbes[id];
      if (probe) {
        expect(
          specs.map((s) => String(s?.name ?? "")),
          `${id} does not serve ${probe}, the read probe its meta/mcp.yml declares`
        ).toContain(probe);
      }
    }
  });
};
