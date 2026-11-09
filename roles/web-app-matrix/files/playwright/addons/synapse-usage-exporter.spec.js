const { test, expect } = require("../onion-test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

test("synapse-usage-exporter addon: the usage metrics never reach the public vhost", async ({ request }) => {
  skipUnlessAddonEnabled("synapse-usage-exporter");
  skipUnlessServiceEnabled("prometheus");

  test.setTimeout(resolveTimeout(60_000));

  const matrixBaseUrl = shared.env.matrixBaseUrl;
  expect(matrixBaseUrl, "MATRIX_BASE_URL must be set").toBeTruthy();

  const metricsUrl = `${matrixBaseUrl.replace(/\/$/, "")}/_synapse/metrics`;
  const response = await request.get(metricsUrl, { failOnStatusCode: false, timeout: resolveTimeout(30_000) });
  const status = response.status();
  const body = await response.text();

  expect(
    status,
    `enabling the usage exporter turns Synapse's own metrics listener on, and that listener carries room counts and ` +
      `user activity. It MUST stay inside the stack for the Prometheus scrape, never on the public vhost at ` +
      `${metricsUrl}. HTTP 200 here means the reverse proxy forwards it to the world. Got HTTP ${status}.`,
  ).not.toBe(200);

  expect(
    body.includes("synapse_build_info") || body.includes("# TYPE synapse"),
    `the public response for ${metricsUrl} must not contain Prometheus exposition text; got: ${body.slice(0, 200)}`,
  ).toBe(false);
});
