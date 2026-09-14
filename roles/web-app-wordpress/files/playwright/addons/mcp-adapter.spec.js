const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

const MCP_ENDPOINT = "/wp-json/mcp/mcp-adapter-default-server";

test("addon mcp-adapter: the MCP endpoint answers nobody without a credential", async ({ browser }) => {
  skipUnlessAddonEnabled("mcp-adapter");
  test.setTimeout(resolveTimeout(60_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    const response = await page.request.post(`${shared.env.wpBaseUrl}${MCP_ENDPOINT}`, {
      failOnStatusCode: false,
      maxRedirects: 0,
      headers: { "content-type": "application/json" },
      data: { jsonrpc: "2.0", id: 1, method: "tools/list" },
    });

    expect(
      response.status(),
      "the adapter authorises through is_user_logged_in(), so an anonymous JSON-RPC call must be refused, never answered",
    ).toBeGreaterThanOrEqual(400);

    expect(
      await response.text(),
      "a refused call must not leak the tool inventory",
    ).not.toContain('"tools"');
  } finally {
    await context.close();
  }
});
