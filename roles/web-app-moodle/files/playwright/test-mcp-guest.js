const { test, expect } = require("@playwright/test");
const { decodeDotenvQuotedValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

const mcpEndpointPath = decodeDotenvQuotedValue(process.env.MCP_ENDPOINT_PATH || "");

exports.register = function (shared) {
  test("guest: the MCP endpoint rejects unauthenticated access", async ({ page }) => {
    skipUnlessServiceEnabled("mcp");

    expect(mcpEndpointPath, "MCP_ENDPOINT_PATH must be set in the Playwright env file").toBeTruthy();

    const endpointUrl = new URL(mcpEndpointPath, shared.env.moodleBaseUrl).toString();
    const response = await page.request.post(endpointUrl, {
      failOnStatusCode: false,
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      data: { jsonrpc: "2.0", id: 1, method: "tools/list", params: {} },
    });

    const status = response.status();
    const body = await response.text();
    const excerpt = body.slice(0, 200);

    expect(status, `${endpointUrl} must be served while the MCP service is enabled`).not.toBe(404);
    expect(
      body.includes('"result"'),
      `an unauthenticated MCP probe must not be served a JSON-RPC result, got ${excerpt}`,
    ).toBe(false);
    expect(
      status >= 400 || body.includes('"error"'),
      `an unauthenticated MCP probe must be rejected, got ${status} with ${excerpt}`,
    ).toBe(true);
  });
};
