const { test, expect } = require("@playwright/test");

const { decodeDotenvQuotedValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { registerMcpDisabledState } = require("./mcp-endpoint");

const MCP_ENDPOINT_PATH = decodeDotenvQuotedValue(process.env.MCP_ENDPOINT_PATH);

exports.register = function (shared) {
  test("guest: the MCP endpoint rejects unauthenticated access", async ({ page }) => {
    skipUnlessServiceEnabled("mcp");

    const baseUrl = shared.expectedMattermostBaseUrl();
    const response = await page.request.post(`${baseUrl}${MCP_ENDPOINT_PATH}`, {
      failOnStatusCode: false,
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json, text/event-stream",
      },
      data: {
        jsonrpc: "2.0",
        id: 1,
        method: "initialize",
        params: {
          protocolVersion: "2025-06-18",
          capabilities: {},
          clientInfo: { name: "infinito-guest-probe", version: "0" },
        },
      },
    });

    expect(
      response.status(),
      "an unauthenticated MCP initialize must not be served a 2xx; the endpoint is bearer-guarded",
    ).toBeGreaterThanOrEqual(400);
  });

  registerMcpDisabledState(() =>
    new URL(MCP_ENDPOINT_PATH, shared.expectedMattermostBaseUrl()).toString(),
  );
};
