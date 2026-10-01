const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { expectHstsWhenTls } = require("./personas");

exports.register = function (shared) {
  test("docs front page opens the latest commit under canonical domain with TLS", async ({ request }) => {
    const response = await request.get(`${shared.appBaseUrl}/`, {
      maxRedirects: 0,
      failOnStatusCode: false,
      timeout: resolveTimeout(30_000),
    });
    expect(response.status(), "Expected the front page to redirect").toBe(302);
    expect(
      response.url().includes(shared.canonicalDomain),
      `Expected canonical domain "${shared.canonicalDomain}" to back the docs URL`,
    ).toBe(true);
    expect(response.headers()["location"], "Expected the front page to open the latest commit").toBe("/latest/");
    expectHstsWhenTls(response.headers(), shared.appBaseUrl, "docs");
  });

  test("the deployed working tree is either the built Sphinx site or its running build", async ({ request }) => {
    const response = await request.get(`${shared.appBaseUrl}/deployed/`, {
      failOnStatusCode: false,
      timeout: resolveTimeout(30_000),
    });
    const body = await response.text();
    expect([200, 202], "Expected the built site or the build page").toContain(response.status());
    const built = response.status() === 200;
    expect(body, "Expected the Sphinx site or the build page of the deployed working tree").toContain(
      built ? 'data-current="deployed"' : 'data-build="deployed"',
    );
    expect(body, "Expected the project title or a progress bar").toContain(built ? "Infinito.Nexus" : "<progress");
  });
};
