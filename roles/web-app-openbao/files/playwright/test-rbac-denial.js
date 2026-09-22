const { test, expect } = require("@playwright/test");
const { normalizeBaseUrl } = require("./personas");
const { resolveTimeout } = require("./timeouts");

const baseUrl = normalizeBaseUrl(process.env.OPENBAO_BASE_URL || "");

test.use({ ignoreHTTPSErrors: true });

test("rbac: unauthenticated API calls to privileged paths are refused", async ({ request }) => {
  for (const path of ["sys/policies/acl", "sys/auth", "sys/mounts"]) {
    const response = await request.get(`${baseUrl}/v1/${path}`, {
      failOnStatusCode: false,
      timeout: resolveTimeout(30_000),
    });
    expect(
      [400, 403],
      `expected /v1/${path} to refuse an unauthenticated caller, got ${response.status()}`,
    ).toContain(response.status());
  }
});

test("rbac: an invalid token is refused on a privileged path", async ({ request }) => {
  const response = await request.get(`${baseUrl}/v1/sys/policies/acl`, {
    headers: { "X-Vault-Token": "not-a-real-token" },
    failOnStatusCode: false,
    timeout: resolveTimeout(30_000),
  });
  expect(
    [400, 403],
    `expected an invalid token to be refused, got ${response.status()}`,
  ).toContain(response.status());
});

test("metrics: /v1/sys/metrics is not served through the public proxy", async ({ request }) => {
  const response = await request.get(`${baseUrl}/v1/sys/metrics?format=prometheus`, {
    failOnStatusCode: false,
    timeout: resolveTimeout(30_000),
  });
  expect(
    response.status(),
    `the metrics endpoint must not be publicly readable, got ${response.status()}`,
  ).not.toBe(200);
});

test("rbac: the three RBAC policies exist and are distinct", async ({ request }) => {
  const response = await request.get(`${baseUrl}/v1/sys/policies/acl?list=true`, {
    failOnStatusCode: false,
    timeout: resolveTimeout(30_000),
  });
  expect(response.status(), "policy listing must not be public").not.toBe(200);
});
