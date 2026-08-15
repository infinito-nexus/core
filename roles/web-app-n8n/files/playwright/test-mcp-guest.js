const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { decodeDotenvQuotedValue, normalizeBaseUrl } = require("./personas");

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const mcpEndpointPath = decodeDotenvQuotedValue(process.env.MCP_ENDPOINT_PATH || "");

test.use({ ignoreHTTPSErrors: true });

test("guest: the managed MCP trigger answers nobody without its bearer", async ({ page }) => {
  skipUnlessServiceEnabled("mcp");
  expect(mcpEndpointPath, "MCP_ENDPOINT_PATH must be set").toBeTruthy();

  const response = await page.request.get(`${appBaseUrl}${mcpEndpointPath}`, {
    failOnStatusCode: false,
    maxRedirects: 0,
    headers: { accept: "text/event-stream" },
  });

  expect(
    response.status(),
    "the trigger is bearerAuth-guarded and stays deactivated until an operator opts in, so an anonymous probe must never receive a stream",
  ).toBeGreaterThanOrEqual(300);

  expect(
    response.headers()["content-type"] || "",
    "a refused probe must not open the SSE channel",
  ).not.toContain("text/event-stream");
});
