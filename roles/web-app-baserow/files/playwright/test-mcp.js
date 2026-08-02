const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { normalizeBaseUrl } = require("./personas");

const UNKNOWN_ENDPOINT_KEY = "0".repeat(32);

test.use({ ignoreHTTPSErrors: true });

test("mcp: an unauthenticated probe of the MCP endpoint is rejected", async ({ page }) => {
  skipUnlessServiceEnabled("mcp");

  const baseUrl = normalizeBaseUrl(process.env.BASEROW_BASE_URL || "");
  expect(baseUrl, "BASEROW_BASE_URL must be set").toBeTruthy();

  const response = await page.request.get(`${baseUrl}/mcp/${UNKNOWN_ENDPOINT_KEY}/sse`, {
    failOnStatusCode: false,
  });

  expect(
    response.headers()["content-type"] || "",
    "a probe carrying no valid endpoint key must never be upgraded to the MCP stream",
  ).not.toContain("text/event-stream");
  expect(
    await response.text(),
    "a probe carrying no valid endpoint key must never receive an MCP session endpoint",
  ).not.toContain("event: endpoint");
});
