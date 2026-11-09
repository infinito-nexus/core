const { test, expect } = require("@playwright/test");
const { normalizeBaseUrl, decodeDotenvQuotedValue, requireDotenvValue } = require("../personas");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { resolveTimeout } = require("../timeouts");

const baseUrl = normalizeBaseUrl(requireDotenvValue(process.env.OPENBAO_BASE_URL, "OPENBAO_BASE_URL"));
const adminUsername = decodeDotenvQuotedValue(requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME"));
const adminPassword = decodeDotenvQuotedValue(requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD"));

test.use({ ignoreHTTPSErrors: true });

test("addon auth-ldap: the ldap mount is served by the external plugin", async ({ request }) => {
  skipUnlessAddonEnabled("auth-ldap");

  const login = await request.post(
    `${baseUrl}/v1/auth/ldap/login/${encodeURIComponent(adminUsername)}`,
    { data: { password: adminPassword }, failOnStatusCode: false, timeout: resolveTimeout(30_000) },
  );
  expect(
    login.status(),
    `expected the LDAP plugin to accept the administrator, got ${login.status()}`,
  ).toBe(200);
  const token = (await login.json()).auth.client_token;

  const mounts = await request.get(`${baseUrl}/v1/sys/auth`, {
    headers: { "X-Vault-Token": token },
    failOnStatusCode: false,
    timeout: resolveTimeout(30_000),
  });
  expect(
    mounts.status(),
    `expected the administrator policy to read sys/auth, got ${mounts.status()}`,
  ).toBe(200);

  const ldap = (await mounts.json()).data["ldap/"];
  expect(ldap, "sys/auth must list the ldap/ mount").toBeTruthy();
  expect(
    ldap.plugin_version,
    "the mount must follow whichever plugin version the image ships",
  ).toBe("latest");
  expect(
    ldap.running_plugin_version,
    "an external plugin reports its own semantic version",
  ).toMatch(/^v\d+\.\d+\.\d+/);
});
