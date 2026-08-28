/**
 * Shared disabled-state assertion for MCP endpoints.
 *
 * Every role-local MCP spec gates itself on `MCP_SERVICE_ENABLED` and skips
 * when the surface is off, so nothing ever checked that switching it off
 * actually removes it. A surface still serving after the flag went false is
 * indistinguishable from one that was never deployed, which is the failure
 * this registers a test for.
 *
 * The check is deliberately transport-agnostic. Roles serve over classic SSE,
 * Streamable HTTP or plain JSON-RPC and their enabled-state specs differ
 * accordingly, but an endpoint that is gone answers none of them, so both a
 * GET and a POST have to come back unserved.
 *
 * Contract:
 *   registerMcpDisabledState(() => endpointUrl) -> registers one Playwright test
 *
 * The URL is passed as a thunk because the roles build it differently and some
 * of them resolve it from fixtures that only exist once a test is running.
 */

const { test, expect } = require("@playwright/test");
const { skipUnlessServiceDisabled } = require("./service-gating");

const SERVED = new Set([200, 201, 202, 401, 403, 405, 406, 415, 429]);

function registerMcpDisabledState(resolveEndpointUrl) {
  test("guest: the MCP endpoint is gone while the service is switched off", async ({
    page,
  }) => {
    skipUnlessServiceDisabled("mcp");

    const endpointUrl = resolveEndpointUrl();
    expect(endpointUrl, "the MCP endpoint URL must resolve even while disabled").toBeTruthy();

    const attempts = [
      await page.request.get(endpointUrl, {
        failOnStatusCode: false,
        maxRedirects: 0,
        headers: { accept: "text/event-stream" },
      }),
      await page.request.post(endpointUrl, {
        failOnStatusCode: false,
        maxRedirects: 0,
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        data: { jsonrpc: "2.0", id: 1, method: "tools/list", params: {} },
      }),
    ];

    for (const response of attempts) {
      const status = response.status();
      const excerpt = (await response.text()).slice(0, 200);
      expect(
        SERVED.has(status),
        `${endpointUrl} answered ${status} with ${excerpt} while MCP is disabled; ` +
          `a refused credential still means the surface is listening`,
      ).toBe(false);
      expect(
        response.headers()["content-type"] || "",
        "a disabled endpoint must not open the SSE channel",
      ).not.toContain("text/event-stream");
    }
  });
}

module.exports = { registerMcpDisabledState };
