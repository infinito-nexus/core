const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { mcpEndpointUrl, registerMcpDisabledState } = require("./mcp-endpoint");
const { decodeDotenvQuotedValue } = require("./personas");

const mcpEndpointPath = decodeDotenvQuotedValue(process.env.MCP_ENDPOINT_PATH || "");
const resolveEndpointUrl = () => mcpEndpointUrl(mcpEndpointPath, process.env.N8N_BASE_URL);

exports.register = function () {
  test("guest: the public vhost refuses the internal MCP trigger to every unauthenticated caller", async ({ page }) => {
    skipUnlessServiceEnabled("mcp");
    expect(mcpEndpointPath, "MCP_ENDPOINT_PATH must be set").toBeTruthy();

    const response = await page.request.get(resolveEndpointUrl(), {
      failOnStatusCode: false,
      maxRedirects: 0,
      headers: { accept: "text/event-stream" },
    });

    expect(
      response.status(),
      "n8n's MCP trigger is exposure: internal, so the public vhost must answer 404; the bearer guard itself is proven in-cluster by the CLI MCP contract",
    ).toBe(404);
  });

  registerMcpDisabledState(resolveEndpointUrl);
};
