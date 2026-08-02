const { test, expect } = require("@playwright/test");

const { skipUnlessServiceEnabled } = require("./service-gating");

exports.register = function (shared) {
  test("mcp: the agent API holding the MCP credentials refuses an unauthenticated caller", async ({ request }) => {
    skipUnlessServiceEnabled("mcp");

    const anonymous = await request.get(`${shared.env.baseUrl}/v1/models`);
    expect(
      anonymous.status(),
      "an unauthenticated /v1/models must be refused; the agent holds one bearer per MCP server",
    ).toBeGreaterThanOrEqual(400);

    expect(
      await anonymous.text(),
      "a refused request must not leak the configured MCP servers",
    ).not.toContain("mcp");

    expect(
      shared.env.apiServerKey,
      "HERMES_API_SERVER_KEY must be set for the authenticated leg of this test",
    ).toBeTruthy();

    const authenticated = await request.get(`${shared.env.baseUrl}/v1/models`, {
      headers: { Authorization: `Bearer ${shared.env.apiServerKey}` },
    });
    expect(
      authenticated.status(),
      "the API server key must open the same endpoint that the anonymous call was refused on",
    ).toBeLessThan(400);
  });
};
