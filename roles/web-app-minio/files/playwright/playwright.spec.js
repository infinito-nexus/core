const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");

const { decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, runBiberFlow, runGuestFlow } = require("./personas");
test.use({ ignoreHTTPSErrors: true });

function parseStsAssumeRoleResponse(body) {
  const match = body.match(/<AccessKeyId>([^<]+)<\/AccessKeyId>[\s\S]*?<SecretAccessKey>([^<]+)<\/SecretAccessKey>[\s\S]*?<SessionToken>([^<]+)<\/SessionToken>/);
  if (!match) return null;
  return {
    accessKey: match[1],
    secretKey: match[2],
    sessionToken: match[3]
  };
}

async function minioConsoleFormLogin(page, baseUrl, username, password) {
  await gotoOnion(page, `${baseUrl}/login`, { waitUntil: "domcontentloaded" });

  const usernameField = page
    .locator("input[name='accessKey'], input[name='username'], input#accessKey, input#username")
    .first();
  const passwordField = page
    .locator("input[name='secretKey'], input[name='password'], input#secretKey, input#password")
    .first();
  const submitButton = page
    .locator("button[type='submit'], input[type='submit']")
    .first();

  await expect(usernameField, "expected MinIO Console login form").toBeVisible({ timeout: resolveTimeout(60_000) });
  await usernameField.fill(username);
  await passwordField.fill(password);
  await submitButton.click({ timeout: resolveTimeout(30_000) });
}

async function minioConsoleLogout(page, baseUrl) {
  await gotoOnion(page, `${baseUrl}/api/v1/logout`, { waitUntil: "commit" }).catch(() => {});
  await page.context().clearCookies();
}

const consoleBaseUrl = normalizeBaseUrl(process.env.MINIO_CONSOLE_URL || "");
const apiBaseUrl = normalizeBaseUrl(process.env.MINIO_API_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const oidcClientId = decodeDotenvQuotedValue(process.env.OIDC_CLIENT_ID || "");
const oidcClientSecret = decodeDotenvQuotedValue(process.env.OIDC_CLIENT_SECRET || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN);

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });

  expect(consoleBaseUrl, "MINIO_CONSOLE_URL must be set").toBeTruthy();
  expect(apiBaseUrl, "MINIO_API_URL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();

  await page.context().clearCookies();
});

test("minio console serves canonical domain over HTTPS", async ({ page }) => {
  const response = await gotoOnion(page, `${consoleBaseUrl}/`);
  expect(response, "Expected MinIO Console landing response").toBeTruthy();
  expect(response.status(), "Expected MinIO Console landing response to be successful").toBeLessThan(400);

  const documentUrl = response.url();
  expect(
    documentUrl.includes(canonicalDomain),
    `Expected canonical domain "${canonicalDomain}" (from applications lookup) to back the MinIO Console URL`
  ).toBe(true);

  await expect(page.locator("body")).toBeVisible({ timeout: resolveTimeout(60_000) });
});

test("administrator: OIDC integrated login path via STS AssumeRoleWithWebIdentity", async ({ request }) => {
  // The MinIO upstream Console pinned by this role does not render
  // the SSO button on its login form (`/api/v1/login` returns
  // `redirectRules: null` regardless of how the OIDC IdP is
  // registered server-side). The integrated OIDC login path for
  // MinIO is therefore exercised at the STS API tier per requirement
  // 013's per-role notes:
  //
  //   1. Obtain an id_token from Keycloak via the password grant
  //      using the role's OIDC client credentials.
  //   2. Exchange the id_token for temporary S3 credentials via
  //      MinIO STS `AssumeRoleWithWebIdentity`. MinIO maps the
  //      Keycloak `policy` / `groups` claim to the
  //      `roles/<role>/administrator` policy created at deploy time.
  //   3. The presence of `AccessKeyId` in the STS response proves
  //      OIDC + RBAC mapping are working end-to-end.
  skipUnlessServiceEnabled("sso");
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set when OIDC is enabled").toBeTruthy();
  expect(oidcClientId, "OIDC_CLIENT_ID must be set when OIDC is enabled").toBeTruthy();
  expect(oidcClientSecret, "OIDC_CLIENT_SECRET must be set when OIDC is enabled").toBeTruthy();

  const tokenResponse = await request.post(`${oidcIssuerUrl}/protocol/openid-connect/token`, {
    form: {
      grant_type: "password",
      client_id: oidcClientId,
      client_secret: oidcClientSecret,
      username: adminUsername,
      password: adminPassword,
      scope: "openid profile email groups"
    }
  });
  expect(tokenResponse.status(), "Keycloak token exchange MUST succeed").toBeLessThan(400);
  const tokenJson = await tokenResponse.json();
  expect(tokenJson.id_token, "Keycloak MUST return an id_token for the OIDC client").toBeTruthy();

  const stsResponse = await request.post(`${apiBaseUrl}/`, {
    params: {
      Action: "AssumeRoleWithWebIdentity",
      Version: "2011-06-15",
      WebIdentityToken: tokenJson.id_token,
      DurationSeconds: "3600"
    }
  });
  expect(stsResponse.status(), "MinIO STS AssumeRoleWithWebIdentity MUST succeed").toBeLessThan(400);
  const body = await stsResponse.text();
  const creds = parseStsAssumeRoleResponse(body);
  expect(creds, `Expected STS XML to contain credentials, got: ${body}`).toBeTruthy();
  expect(creds.accessKey, "STS response MUST include an AccessKeyId").toBeTruthy();
  expect(creds.secretKey, "STS response MUST include a SecretAccessKey").toBeTruthy();
  expect(creds.sessionToken, "STS response MUST include a SessionToken").toBeTruthy();
});

test("administrator: MinIO Console form login under LDAP variant", async ({ page }) => {
  skipUnlessServiceEnabled("ldap");

  await minioConsoleFormLogin(page, consoleBaseUrl, adminUsername, adminPassword);

  await expect(page.locator("body")).toContainText(/object browser|buckets|access keys|monitoring/i, { timeout: resolveTimeout(60_000) });

  await minioConsoleLogout(page, consoleBaseUrl);

  await gotoOnion(page, `${consoleBaseUrl}/login`);
  await expect(
    page
      .locator("input[name='accessKey'], input[name='username'], input#accessKey, input#username")
      .first()
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
});

// Persona scenarios.
// Bodies live in the shared helper roles/test-e2e-playwright/files/personas.js
// so every role's persona flow stays consistent.

test("guest: public-landing → auth chain → never authenticated", async ({ page }) => {
  await runGuestFlow(page);
});

test("biber: app → universal logout", async ({ page }) => {
  await runBiberFlow(page);
});
