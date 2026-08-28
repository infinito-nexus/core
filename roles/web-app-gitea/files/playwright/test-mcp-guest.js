const { test, expect } = require("@playwright/test");

const { skipUnlessServiceEnabled } = require("./service-gating");
const { registerMcpDisabledState } = require("./mcp-endpoint");

exports.register = function (shared) {
  test("mcp: an unauthenticated probe of the MCP endpoint is rejected", async ({ page }) => {
    skipUnlessServiceEnabled("mcp");

    // maxRedirects: 0 because the vhost answers the bearerless probe with an
    // SSO redirect; following it would land on a 200 login page and hide that
    // no MCP response was ever served.
    const response = await page.request.post(shared.mcpEndpointUrl(), {
      failOnStatusCode: false,
      maxRedirects: 0,
      headers: { "Content-Type": "application/json" },
      data: { jsonrpc: "2.0", id: 1, method: "initialize", params: {} },
    });

    expect(
      response.status(),
      `POST ${shared.mcpEndpointUrl()} answered ${response.status()} — ` +
        "the MCP server is internal-only, so the public vhost must redirect or refuse a bearerless initialize, never answer it.",
    ).toBeGreaterThanOrEqual(300);

    expect(
      await response.text(),
      "the public vhost must not return an MCP protocol response to a bearerless probe",
    ).not.toContain('"jsonrpc"');
  });

  registerMcpDisabledState(() => shared.mcpEndpointUrl());
};
