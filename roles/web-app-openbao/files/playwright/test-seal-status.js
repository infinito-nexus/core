const { test, expect } = require("@playwright/test");
const { normalizeBaseUrl } = require("./personas");
const { resolveTimeout } = require("./timeouts");

const baseUrl = normalizeBaseUrl(process.env.OPENBAO_BASE_URL || "");

test.use({ ignoreHTTPSErrors: true });

test("seal: the node reports itself unsealed with a static-seal recovery config", async ({ request }) => {
  const response = await request.get(`${baseUrl}/v1/sys/seal-status`, {
    failOnStatusCode: false,
    timeout: resolveTimeout(30_000),
  });
  expect(response.status(), "seal-status must be readable unauthenticated").toBe(200);

  const status = await response.json();
  expect(status.initialized, "OpenBao must be initialised").toBe(true);
  expect(status.sealed, "the static seal must have auto-unsealed the node").toBe(false);
  // An auto-seal yields recovery keys rather than unseal shares; recovery_seal marks that mode.
  expect(
    status.recovery_seal,
    "an auto-seal must report recovery mode, not Shamir unseal shares",
  ).toBe(true);
});

test("seal: the sealed state is the monitored signal on /v1/sys/health", async ({ request }) => {
  // Contract the monitoring probe relies on: strict codes distinguish sealed (503) from
  // healthy (200). The overridden codes are only used by the container healthcheck.
  const strict = await request.get(`${baseUrl}/v1/sys/health`, {
    failOnStatusCode: false,
    timeout: resolveTimeout(30_000),
  });
  expect(strict.status(), "a healthy unsealed node must answer 200").toBe(200);

  const overridden = await request.get(`${baseUrl}/v1/sys/health?sealedcode=200&uninitcode=200`, {
    failOnStatusCode: false,
    timeout: resolveTimeout(30_000),
  });
  expect(
    overridden.status(),
    "the overridden codes the container healthcheck uses must be accepted",
  ).toBe(200);
});
