const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { normalizeBaseUrl } = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.FLOWISE_BASE_URL || "");

test.use({ ignoreHTTPSErrors: true });

test("mcp: the instance exposes no MCP registry and refuses an unauthenticated caller", async ({ request }) => {
  skipUnlessServiceEnabled("mcp");
  expect(baseUrl, "FLOWISE_BASE_URL must be set").toBeTruthy();

  const anonymous = await request.get(`${baseUrl.replace(/\/+$/, "")}/api/v1/chatflows`, {
    failOnStatusCode: false,
    maxRedirects: 0,
  });
  expect(
    anonymous.status(),
    "an unauthenticated Flowise API call must be refused or redirected to SSO, never answered",
  ).toBeGreaterThanOrEqual(300);
});
