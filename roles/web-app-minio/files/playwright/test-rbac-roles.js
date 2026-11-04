const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceDisabled, skipUnlessServiceEnabled } = require("./service-gating");
const { decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, withLdapGroupMember } = require("./personas");
const keycloakAdmin = require("./personas/utils/keycloak");
const { sign } = require("./personas/utils/s3");

test.use({ ignoreHTTPSErrors: true });

const env = {
  apiBaseUrl: normalizeBaseUrl(process.env.MINIO_API_URL || "").replace(/\/$/, ""),
  consoleBaseUrl: normalizeBaseUrl(process.env.MINIO_CONSOLE_URL || "").replace(/\/$/, ""),
  region: decodeDotenvQuotedValue(process.env.MINIO_REGION),
  oidcIssuerUrl: normalizeBaseUrl(process.env.OIDC_ISSUER_URL || ""),
  oidcClientId: decodeDotenvQuotedValue(process.env.OIDC_CLIENT_ID),
  oidcClientSecret: decodeDotenvQuotedValue(process.env.OIDC_CLIENT_SECRET),
  keycloakBaseUrl: normalizeBaseUrl(process.env.KEYCLOAK_BASE_URL || ""),
  realmName: decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME),
  superAdminUsername: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME),
  superAdminPassword: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD),
  keycloakAdminRealm: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_REALM),
  keycloakAdminCliClientId: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_CLI_CLIENT_ID),
  biberUsername: decodeDotenvQuotedValue(process.env.BIBER_USERNAME),
  biberPassword: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD),
  biberDn: decodeDotenvQuotedValue(process.env.BIBER_LDAP_DN),
  readonlyGroupDn: decodeDotenvQuotedValue(process.env.LDAP_READONLY_GROUP_DN),
  readwriteGroupPath: decodeDotenvQuotedValue(process.env.RBAC_READWRITE_GROUP_PATH),
  readonlyGroupPath: decodeDotenvQuotedValue(process.env.RBAC_READONLY_GROUP_PATH),
};

/**
 * Run `fn` while biber is a member of the Keycloak group at `groupPath`,
 * removing the membership afterwards only when this call granted it.
 *
 * Args:
 *   playwright: the Playwright request factory, used for an isolated admin context.
 *   groupPath: the full Keycloak group path, with leading slash.
 *   fn: async body executed while the membership holds.
 */
async function withBiberInGroup(playwright, groupPath, fn) {
  const adminOpts = { adminRealm: env.keycloakAdminRealm, adminClientId: env.keycloakAdminCliClientId };
  const adminRequest = await playwright.request.newContext({ ignoreHTTPSErrors: true });
  let biberAdded = false;
  try {
    biberAdded = await keycloakAdmin.keycloakAdminAddUserToGroup(
      adminRequest,
      env.keycloakBaseUrl,
      env.realmName,
      groupPath,
      env.biberUsername,
      env.superAdminUsername,
      env.superAdminPassword,
      adminOpts,
    );
    return await fn();
  } finally {
    if (biberAdded) {
      await keycloakAdmin
        .keycloakRemoveUserFromGroupViaRest(
          adminRequest,
          env.keycloakBaseUrl,
          env.realmName,
          env.superAdminUsername,
          env.superAdminPassword,
          groupPath,
          env.biberUsername,
          adminOpts,
        )
        .catch((err) => console.warn(`Cleanup removal of biber from ${groupPath} failed: ${err}`));
    }
    await adminRequest.dispose().catch(() => {});
  }
}

/**
 * Exchange biber's Keycloak id_token for MinIO STS credentials and return
 * the HTTP status plus the parsed credentials, if any.
 *
 * Args:
 *   request: a Playwright APIRequestContext.
 */
async function biberStsCredentials(request) {
  const tokenResponse = await request.post(`${env.oidcIssuerUrl}/protocol/openid-connect/token`, {
    form: {
      grant_type: "password",
      client_id: env.oidcClientId,
      client_secret: env.oidcClientSecret,
      username: env.biberUsername,
      password: env.biberPassword,
      scope: "openid profile email",
    },
    timeout: resolveTimeout(30_000),
  });
  expect(tokenResponse.status(), "Keycloak MUST issue biber an id_token").toBeLessThan(400);
  const idToken = (await tokenResponse.json()).id_token;
  const stsResponse = await request.post(`${env.apiBaseUrl}/`, {
    params: {
      Action: "AssumeRoleWithWebIdentity",
      Version: "2011-06-15",
      WebIdentityToken: idToken,
      DurationSeconds: "900",
    },
    failOnStatusCode: false,
    timeout: resolveTimeout(30_000),
  });
  const body = await stsResponse.text();
  const match = body.match(
    /<AccessKeyId>([^<]+)<\/AccessKeyId>[\s\S]*?<SecretAccessKey>([^<]+)<\/SecretAccessKey>[\s\S]*?<SessionToken>([^<]+)<\/SessionToken>/,
  );
  return {
    status: stsResponse.status(),
    body,
    creds: match ? { accessKey: match[1], secretKey: match[2], sessionToken: match[3] } : null,
  };
}

/**
 * Send one SigV4-signed, path-style S3 request with STS credentials.
 *
 * Args:
 *   request: a Playwright APIRequestContext.
 *   method: the HTTP method.
 *   path: the bucket or object path, starting with a slash.
 *   creds: the STS credentials from biberStsCredentials.
 */
async function s3Call(request, method, path, creds) {
  const url = new URL(env.apiBaseUrl);
  const headers = sign({
    method,
    host: url.host,
    path,
    region: env.region,
    accessKey: creds.accessKey,
    secretKey: creds.secretKey,
    query: {},
  });
  headers["x-amz-security-token"] = creds.sessionToken;
  return request.fetch(`${url.origin}${path}`, {
    method,
    headers,
    failOnStatusCode: false,
    timeout: resolveTimeout(30_000),
  });
}

/**
 * Submit the MinIO Console login form, which authenticates against LDAP
 * in the LDAP variant.
 *
 * Args:
 *   page: the Playwright page to drive.
 *   username: the directory login name.
 *   password: the directory password.
 */
async function submitConsoleLogin(page, username, password) {
  await gotoOnion(page, `${env.consoleBaseUrl}/login`, { waitUntil: "domcontentloaded" });
  const usernameField = page
    .locator("input[name='accessKey'], input[name='username'], input#accessKey, input#username")
    .first();
  await expect(usernameField, "expected MinIO Console login form").toBeVisible({ timeout: resolveTimeout(60_000) });
  await usernameField.fill(username);
  await page
    .locator("input[name='secretKey'], input[name='password'], input#secretKey, input#password")
    .first()
    .fill(password);
  const loginResponse = page.waitForResponse(
    (response) => response.url().includes("/api/v1/login") && response.request().method() === "POST",
    { timeout: resolveTimeout(60_000) },
  );
  await page.locator("button[type='submit'], input[type='submit']").first().click({ timeout: resolveTimeout(30_000) });
  return (await loginResponse).status();
}

test("biber: the LDAP Console login refuses biber without a MinIO role group", async ({ page }) => {
  skipUnlessServiceEnabled("ldap");
  skipUnlessServiceDisabled("sso");
  const status = await submitConsoleLogin(page, env.biberUsername, env.biberPassword);
  expect(status, "biber's directory groups carry no MinIO policy, so the Console login MUST fail").toBeGreaterThanOrEqual(400);
});

test("biber: membership in the readonly group lets biber sign in to the Console through LDAP", async ({ page }) => {
  skipUnlessServiceEnabled("ldap");
  skipUnlessServiceDisabled("sso");
  test.setTimeout(resolveTimeout(120_000)); // directory group write plus the Console login
  await withLdapGroupMember(env.readonlyGroupDn, env.biberDn, async () => {
    const status = await submitConsoleLogin(page, env.biberUsername, env.biberPassword);
    expect(status, "the readonly policy attached to the LDAP role group MUST admit biber to the Console").toBeLessThan(400);
    await expect(page.locator("body")).toContainText(/object browser|buckets/i, { timeout: resolveTimeout(60_000) });
    await page.context().clearCookies();
  });
});

test("rbac: biber without a MinIO role group gets no STS credentials", async ({ request }) => {
  skipUnlessServiceEnabled("sso");
  const sts = await biberStsCredentials(request);
  expect(sts.creds, `biber holds no MinIO policy group, so STS MUST refuse him (status ${sts.status}): ${sts.body.slice(0, 400)}`).toBeNull();
  expect(sts.status, "the STS refusal MUST be an error status").toBeGreaterThanOrEqual(400);
});

test("rbac: membership in the readonly group yields STS credentials that cannot create a bucket", async ({
  request,
  playwright,
}) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(120_000)); // Keycloak group join, token exchange and the S3 probe
  await withBiberInGroup(playwright, env.readonlyGroupPath, async () => {
    const sts = await biberStsCredentials(request);
    expect(sts.creds, `a readonly member MUST receive STS credentials (status ${sts.status}): ${sts.body.slice(0, 400)}`).not.toBeNull();
    const bucket = `/rbac-readonly-${Date.now()}`;
    const create = await s3Call(request, "PUT", bucket, sts.creds);
    expect(create.status(), "the readonly policy MUST refuse bucket creation").toBe(403);
  });
});

test("rbac: membership in the readwrite group yields STS credentials that create and delete a bucket", async ({
  request,
  playwright,
}) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(120_000)); // Keycloak group join, token exchange and the S3 round-trip
  await withBiberInGroup(playwright, env.readwriteGroupPath, async () => {
    const sts = await biberStsCredentials(request);
    expect(sts.creds, `a readwrite member MUST receive STS credentials (status ${sts.status}): ${sts.body.slice(0, 400)}`).not.toBeNull();
    const bucket = `/rbac-readwrite-${Date.now()}`;
    const create = await s3Call(request, "PUT", bucket, sts.creds);
    try {
      expect(create.status(), `the readwrite policy MUST allow bucket creation: ${(await create.text()).slice(0, 400)}`).toBe(200);
    } finally {
      const removal = await s3Call(request, "DELETE", bucket, sts.creds);
      if (![204, 404].includes(removal.status())) {
        console.warn(`Cleanup of bucket ${bucket} answered ${removal.status()}`);
      }
    }
  });
});
