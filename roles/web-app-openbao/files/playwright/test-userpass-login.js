const { test, expect } = require("@playwright/test");
const { normalizeBaseUrl, decodeDotenvQuotedValue, requireDotenvValue } = require("./personas");
const { resolveTimeout } = require("./timeouts");

const baseUrl = normalizeBaseUrl(requireDotenvValue(process.env.OPENBAO_BASE_URL, "OPENBAO_BASE_URL"));
const adminUsername = requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME");
const adminPassword = requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD");
const passwordMount = decodeDotenvQuotedValue(process.env.OPENBAO_PASSWORD_AUTH_MOUNT || "");
const userpassMount = requireDotenvValue(process.env.OPENBAO_USERPASS_MOUNT, "OPENBAO_USERPASS_MOUNT");

test.use({ ignoreHTTPSErrors: true });

const login = (request) =>
  request.post(`${baseUrl}/v1/auth/${userpassMount}/login/${encodeURIComponent(adminUsername)}`, {
    data: { password: adminPassword },
    failOnStatusCode: false,
    timeout: resolveTimeout(30_000),
  });

test("userpass: the administrator signs in with the platform password when no identity provider is deployed", async ({
  request,
}) => {
  test.skip(
    passwordMount !== userpassMount,
    "an identity provider carries the administrator sign-in (OPENBAO_PASSWORD_AUTH_MOUNT is not the userpass mount)",
  );

  const response = await login(request);
  expect(
    response.status(),
    `expected the userpass method to accept the administrator, got ${response.status()}`,
  ).toBe(200);

  const { auth } = await response.json();
  try {
    expect(auth.policies, "the userpass account must carry the administrator policy").toContain("administrator");
    for (const tier of ["operator", "reader"]) {
      expect(auth.policies, `the userpass account must not carry the ${tier} policy`).not.toContain(tier);
    }
  } finally {
    await request.post(`${baseUrl}/v1/auth/token/revoke-self`, {
      headers: { "X-Vault-Token": auth.client_token },
      failOnStatusCode: false,
      timeout: resolveTimeout(30_000),
    });
  }
});

test("userpass: the method is absent while an identity provider carries the sign-in", async ({ request }) => {
  test.skip(
    passwordMount === userpassMount,
    "the userpass method carries the administrator sign-in (OPENBAO_PASSWORD_AUTH_MOUNT is the userpass mount)",
  );

  const response = await login(request);
  expect(
    response.status(),
    `a deployment with an identity provider must offer no userpass login, got ${response.status()}`,
  ).not.toBe(200);
});
