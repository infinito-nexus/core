const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { decodeDotenvQuotedValue, normalizeBaseUrl } = require("./personas");
const { registerMcpDisabledState } = require("./mcp-endpoint");

const baseUrl = normalizeBaseUrl(process.env.JENKINS_BASE_URL || "");
const mcpEndpointPath = decodeDotenvQuotedValue(process.env.MCP_ENDPOINT_PATH || "");

test.use({ ignoreHTTPSErrors: true });

test("MCP: the plugin endpoint serves no tool without credentials", async ({ page }) => {
  skipUnlessServiceEnabled("mcp");
  expect(mcpEndpointPath, "MCP_ENDPOINT_PATH must be set").toBeTruthy();

  const response = await page.request.post(`${baseUrl.replace(/\/$/, "")}${mcpEndpointPath}`, {
    failOnStatusCode: false,
    headers: { "Content-Type": "application/json", Accept: "application/json, text/event-stream" },
    data: { jsonrpc: "2.0", id: 1, method: "tools/list", params: {} },
  });

  expect(
    response.status(),
    "an unauthenticated tools/list must not be served a 2xx; the tool surface is credential-guarded",
  ).toBeGreaterThanOrEqual(400);

  expect(
    await response.text(),
    "a refused tools/list must not leak a tool inventory",
  ).not.toContain('"tools"');
});

registerMcpDisabledState(
  () => `${baseUrl.replace(/\/$/, "")}${mcpEndpointPath}`,
);
