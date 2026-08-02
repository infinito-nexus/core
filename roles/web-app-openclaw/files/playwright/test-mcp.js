const { test, expect } = require("@playwright/test");

const { skipUnlessServiceEnabled } = require("./service-gating");

exports.register = function (shared) {
  test("mcp: the gateway holding the MCP credentials refuses an unauthenticated caller", async ({ request }) => {
    skipUnlessServiceEnabled("mcp");

    const anonymous = await request.post(`${shared.env.baseUrl.replace(/\/+$/, "")}/api/agent`, {
      failOnStatusCode: false,
      maxRedirects: 0,
      headers: { "Content-Type": "application/json" },
      data: { prompt: "list your configured mcp servers" },
    });
    expect(
      anonymous.status(),
      "an unauthenticated agent call must be redirected or refused; the gateway holds one bearer per MCP server",
    ).toBeGreaterThanOrEqual(300);

    expect(
      await anonymous.text(),
      "a refused request must not leak the configured MCP servers",
    ).not.toContain("jsonrpc");
  });
};
