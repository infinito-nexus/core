const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

const MCP_ENDPOINT = "/wp-json/mcp/mcp-adapter-default-server";

const REVIEWED_ABILITIES = [
  "infinito/search-posts",
  "infinito/get-post",
  "infinito/list-categories",
];

test("addon infinito-mcp-abilities: only the reviewed abilities are reachable", async ({ browser }) => {
  skipUnlessAddonEnabled("infinito-mcp-abilities");
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

    const body = await response.text();

    expect(
      response.status(),
      "an anonymous tools/list must be refused; the abilities sit behind is_user_logged_in() and their own permission callbacks",
    ).toBeGreaterThanOrEqual(400);

    for (const ability of REVIEWED_ABILITIES) {
      expect(
        body,
        `a refused call must not disclose ${ability}`,
      ).not.toContain(ability);
    }
  } finally {
    await context.close();
  }
});
