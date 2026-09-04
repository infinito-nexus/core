const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const shared = require("./_shared");
const { registerMcpDisabledState } = require("./mcp-endpoint");

const MCP_ENDPOINT = "/wp-json/mcp/mcp-adapter-default-server";

test.use({ ignoreHTTPSErrors: true });

test("guest: the MCP endpoint rejects unauthenticated access", async ({ page }) => {
  skipUnlessServiceEnabled("mcp");

  const response = await page.request.post(`${shared.env.wpBaseUrl}${MCP_ENDPOINT}`, {
    failOnStatusCode: false,
    maxRedirects: 0,
    headers: { "content-type": "application/json" },
    data: { jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18" } },
  });

  expect(
    response.status(),
    "the adapter authorises through is_user_logged_in(), so an anonymous MCP probe must never be answered",
  ).toBeGreaterThanOrEqual(400);

  expect(
    await response.text(),
    "a refused probe must not return an MCP protocol response",
  ).not.toContain('"jsonrpc"');
});

registerMcpDisabledState(() => `${shared.env.wpBaseUrl}${MCP_ENDPOINT}`);
