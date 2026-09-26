const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { expectHstsWhenTls, gotoOnion } = require("./personas");

exports.register = function (shared) {
  test("docs front page opens the latest commit under canonical domain with TLS", async ({ page }) => {
    const response = await gotoOnion(page, `${shared.appBaseUrl}/`);
    expect(response, "Expected docs response").toBeTruthy();
    expect(response.status(), "Expected docs front page status < 400").toBeLessThan(400);
    expect(
      response.url().includes(shared.canonicalDomain),
      `Expected canonical domain "${shared.canonicalDomain}" to back the docs URL`,
    ).toBe(true);
    expect(new URL(response.url()).pathname, "Expected the front page to open the latest commit").toBe("/latest/");
    expectHstsWhenTls(response.headers(), shared.appBaseUrl, "docs");
  });

  test("latest commit is either the built Sphinx site or its running build", async ({ request }) => {
    const response = await request.get(`${shared.appBaseUrl}/latest/`, { timeout: resolveTimeout(30_000) });
    const body = await response.text();
    expect([200, 202], "Expected the built site or the build page").toContain(response.status());
    const built = response.status() === 200;
    expect(body, "Expected the Sphinx site or the build page of the latest commit").toContain(
      built ? 'data-current="latest"' : 'data-build="latest"',
    );
    expect(body, "Expected the project title or a progress bar").toContain(built ? "Infinito.Nexus" : "<progress");
  });
};
