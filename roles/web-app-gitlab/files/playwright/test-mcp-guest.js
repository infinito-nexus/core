const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { decodeDotenvQuotedValue, normalizeBaseUrl } = require("./personas");
const { registerMcpDisabledState } = require("./mcp-endpoint");

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const mcpEndpointPath = decodeDotenvQuotedValue(process.env.MCP_ENDPOINT_PATH || "");

test.use({ ignoreHTTPSErrors: true });

test("guest: the MCP endpoint rejects unauthenticated access", async ({ page }) => {
  skipUnlessServiceEnabled("mcp");
  expect(mcpEndpointPath, "MCP_ENDPOINT_PATH must be set").toBeTruthy();

  const response = await page.request.post(`${appBaseUrl}${mcpEndpointPath}`, {
    failOnStatusCode: false,
    maxRedirects: 0,
    headers: { "content-type": "application/json" },
    data: { jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18" } },
  });

  expect(
    response.status(),
    "an unauthenticated MCP probe must be refused or redirected, never answered; the endpoint is token-guarded",
  ).toBeGreaterThanOrEqual(300);

  expect(
    await response.text(),
    "a refused probe must not return an MCP protocol response",
  ).not.toContain('"jsonrpc"');
});

registerMcpDisabledState(() => `${appBaseUrl}${mcpEndpointPath}`);
