const { test, expect } = require("@playwright/test");
const { expectHstsWhenTls } = require("./personas");

exports.register = function (shared) {
  test("health answers on the canonical domain with TLS and open CORS", async ({ request }) => {
    const { response, body } = await shared.getJson(request, "/v1/health");
    expect(response.url(), "Expected the canonical API domain").toContain(shared.canonicalDomain);
    expect(body.status).toBe("ok");
    expect(body.deployed, "Expected the deployed snapshot commit").toMatch(/^[0-9a-f]{40}$/);
    expect(response.headers()["access-control-allow-origin"], "Expected open CORS").toBe("*");
    expectHstsWhenTls(response.headers(), shared.appBaseUrl, "api");
  });

  test("only GET, HEAD and OPTIONS are accepted", async ({ request }) => {
    expect(await shared.statusOf(request, "/v1/health", {}, "HEAD")).toBe(200);
    for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {
      expect(await shared.statusOf(request, "/v1/health", {}, method), `Expected ${method} to be refused`).toBe(405);
    }
    const preflight = await request.fetch(shared.apiUrl("/v1/roles", { ref: "deployed" }), {
      method: "OPTIONS",
      headers: { Origin: "https://example.org", "Access-Control-Request-Method": "GET" },
      failOnStatusCode: false,
    });
    expect(preflight.status(), "Expected the CORS preflight to succeed").toBe(200);
    expect(preflight.headers()["access-control-allow-origin"]).toBe("*");
  });
};
