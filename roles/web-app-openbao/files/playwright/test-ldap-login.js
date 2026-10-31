const { test, expect } = require("@playwright/test");
const {
  normalizeBaseUrl,
  requireDotenvValue,
} = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const baseUrl = normalizeBaseUrl(requireDotenvValue(process.env.OPENBAO_BASE_URL, "OPENBAO_BASE_URL"));
const adminUsername = requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME");
const adminPassword = requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD");
const biberUsername = requireDotenvValue(process.env.BIBER_USERNAME, "BIBER_USERNAME");
const biberPassword = requireDotenvValue(process.env.BIBER_PASSWORD, "BIBER_PASSWORD");

test.use({ ignoreHTTPSErrors: true });

test("ldap: the administrator logs in and receives the administrator policy", async ({ request }) => {
  skipUnlessServiceEnabled("ldap");

  const response = await request.post(
    `${baseUrl}/v1/auth/ldap/login/${encodeURIComponent(adminUsername)}`,
    { data: { password: adminPassword }, failOnStatusCode: false, timeout: resolveTimeout(30_000) },
  );
  expect(
    response.status(),
    `expected the LDAP auth method to accept the administrator, got ${response.status()}`,
  ).toBe(200);

  const body = await response.json();
  expect(
    body.auth.policies,
    "the administrator's LDAP group must map to the administrator policy",
  ).toContain("administrator");
});

test("ldap: a user in no OpenBao role group gets no privileged policy", async ({ request }) => {
  skipUnlessServiceEnabled("ldap");

  const response = await request.post(
    `${baseUrl}/v1/auth/ldap/login/${encodeURIComponent(biberUsername)}`,
    { data: { password: biberPassword }, failOnStatusCode: false, timeout: resolveTimeout(30_000) },
  );

  if (response.status() === 200) {
    const body = await response.json();
    const policies = body.auth.policies || [];
    expect(policies, "biber must not receive the administrator policy").not.toContain("administrator");
    expect(policies, "biber must not receive the operator policy").not.toContain("operator");
  } else {
    expect(
      [400, 403],
      `expected a clean denial for a user outside every role group, got ${response.status()}`,
    ).toContain(response.status());
  }
});
