const { test, expect } = require("@playwright/test");
const { decodeDotenvQuotedValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { registerMcpDisabledState } = require("./mcp-endpoint");

const mcpEndpointPath = decodeDotenvQuotedValue(process.env.NEXTCLOUD_MCP_ENDPOINT_PATH);

exports.register = function (shared) {
  test("guest: the MCP endpoint rejects unauthenticated access", async ({ page }) => {
    skipUnlessServiceEnabled("mcp");

    expect(mcpEndpointPath, "NEXTCLOUD_MCP_ENDPOINT_PATH must be set in the Playwright env file").toBeTruthy();

    const endpointUrl = new URL(mcpEndpointPath, shared.env.nextcloudBaseUrl).toString();
    const response = await page.request.post(endpointUrl, {
      failOnStatusCode: false,
      headers: {
        Accept: "application/json, text/event-stream",
        "Content-Type": "application/json",
      },
      data: {
        jsonrpc: "2.0",
        id: 1,
        method: "initialize",
        params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "playwright", version: "1" } },
      },
    });

    expect(
      response.status(),
      "an unauthenticated MCP probe must not be served a 2xx; the endpoint is app-password guarded",
    ).toBeGreaterThanOrEqual(400);
  });

  registerMcpDisabledState(() =>
    new URL(mcpEndpointPath, shared.env.nextcloudBaseUrl).toString(),
  );
};
