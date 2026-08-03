const { test, expect } = require("@playwright/test");

const { skipUnlessServiceEnabled } = require("./service-gating");

exports.register = function (shared) {
  test("mcp: an unauthenticated probe of the MCP endpoint is rejected", async ({ request }) => {
    skipUnlessServiceEnabled("mcp");

    const response = await request.post(`${shared.env.baseUrl.replace(/\/+$/, "")}/api/mcp`, {
      failOnStatusCode: false,
      maxRedirects: 0,
      headers: { "Content-Type": "application/json", Accept: "application/json, text/event-stream" },
      data: { jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18" } },
    });

    expect(
      response.status(),
      "an unauthenticated MCP probe must be refused or redirected, never answered; Home Assistant answers 404 so the endpoint is not even disclosed",
    ).toBeGreaterThanOrEqual(300);

    expect(
      await response.text(),
      "a refused probe must not return an MCP protocol response",
    ).not.toContain('"jsonrpc"');
  });
};
