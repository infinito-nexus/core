const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { baseUrl, fetchPluginRecord, loginAsAdministrator } = require("../jenkins-login");

test.use({ ignoreHTTPSErrors: true });

test("addon prometheus: the metrics plugin is active and its endpoint is not public", async ({ page, playwright }) => {
  skipUnlessAddonEnabled("prometheus");
  test.setTimeout(resolveTimeout(180_000));

  await loginAsAdministrator(page);

  const plugin = await fetchPluginRecord(page, "prometheus");
  expect(
    plugin,
    "the plugin manager must list 'prometheus'; it is absent when the addon declaration did not " +
      "reach templates/plugins.txt.j2 and jenkins-plugin-cli never fetched it",
  ).toBeTruthy();
  expect(plugin.active, "the prometheus plugin must be active, not merely downloaded").toBe(true);

  const anonymous = await playwright.request.newContext({ ignoreHTTPSErrors: true });
  const metrics = await anonymous.get(`${baseUrl}/prometheus`, {
    timeout: resolveTimeout(60_000),
  });
  const body = await metrics.text();
  await anonymous.dispose();

  expect(
    metrics.status(),
    `an anonymous visitor must not read the scrape endpoint on the public vhost; web-app-prometheus ` +
      `reaches it on the internal container port instead (see templates/prometheus.yml.j2). Got ` +
      `${metrics.status()} with ${body.length} bytes`,
  ).toBeGreaterThanOrEqual(400);
  expect(
    body,
    "an anonymous refusal must not leak the metrics it refuses",
  ).not.toMatch(/^#\s*HELP/m);
});
