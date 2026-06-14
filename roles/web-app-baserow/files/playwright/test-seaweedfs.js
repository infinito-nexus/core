// SeaweedFS object-store scenario for Baserow.
//
// Baserow stores uploaded user files through django-storages when AWS_* is set.
// The test uses Baserow's API instead of brittle grid UI selectors: after the
// OIDC gate provisions a native Baserow JWT, it creates a database, a table, a
// File field, uploads a document, and stores it in a row. The shared SeaweedFS
// check proves that the configured bucket gained an object.

const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const {
  runSeaweedfsStorageCheck,
  performKeycloakLoginForm,
  normalizeBaseUrl,
  decodeDotenvQuotedValue,
} = require("./personas");

test.use({ ignoreHTTPSErrors: true });

async function readJson(response, label) {
  const body = await response.text();
  expect(response.ok(), `${label} failed with ${response.status()}: ${body}`).toBe(true);
  return body ? JSON.parse(body) : null;
}

async function getBaserowSession(appPage, baseUrl, adminUsername, adminPassword) {
  await appPage.context().clearCookies();
  await appPage.goto(`${baseUrl}/`, { waitUntil: "domcontentloaded" });

  if (/openid-connect\/auth|\/oauth2\//.test(appPage.url())) {
    await performKeycloakLoginForm(appPage, adminUsername, adminPassword);
  }

  await expect
    .poll(() => appPage.url(), { timeout: 90_000, message: `expected redirect back to ${baseUrl}` })
    .toContain(baseUrl.replace(/^https?:\/\//, ""));
  await appPage.waitForLoadState("networkidle", { timeout: 60_000 }).catch(() => {});

  const tokenResponse = await appPage.request.get(`${baseUrl}/api/infinito/sso/token/`);
  const tokenData = await readJson(tokenResponse, "trusted-header token request");
  expect(tokenData.access_token, "Baserow access token must be present").toBeTruthy();
  return tokenData;
}

async function createBaserowFileRow(appPage, baseUrl, accessToken) {
  const jsonHeaders = {
    Authorization: `JWT ${accessToken}`,
    "Content-Type": "application/json",
  };
  const authHeaders = { Authorization: `JWT ${accessToken}` };
  const stamp = Date.now();
  const marker = `infinito-storage-check-${stamp}.txt`;

  const workspaces = await readJson(
    await appPage.request.get(`${baseUrl}/api/workspaces/`, { headers: authHeaders }),
    "workspace list",
  );
  expect(workspaces.length, "SSO user must have a workspace").toBeGreaterThan(0);
  const workspaceId = workspaces[0].id;

  const database = await readJson(
    await appPage.request.post(`${baseUrl}/api/applications/workspace/${workspaceId}/`, {
      headers: jsonHeaders,
      data: { name: `Storage Check ${stamp}`, type: "database" },
    }),
    "database creation",
  );

  const table = await readJson(
    await appPage.request.post(`${baseUrl}/api/database/tables/database/${database.id}/`, {
      headers: jsonHeaders,
      data: { name: "Files", first_row_header: false },
    }),
    "table creation",
  );

  const fileField = await readJson(
    await appPage.request.post(`${baseUrl}/api/database/fields/table/${table.id}/`, {
      headers: jsonHeaders,
      data: { name: "Attachment", type: "file" },
    }),
    "file field creation",
  );

  const upload = await readJson(
    await appPage.request.post(`${baseUrl}/api/user-files/upload-file/`, {
      headers: authHeaders,
      multipart: {
        file: {
          name: marker,
          mimeType: "text/plain",
          buffer: Buffer.from(`infinito storage check ${marker}`),
        },
      },
    }),
    "file upload",
  );
  expect(upload.name, "Baserow must return an internal uploaded-file name").toBeTruthy();

  const row = await readJson(
    await appPage.request.post(`${baseUrl}/api/database/rows/table/${table.id}/?user_field_names=true`, {
      headers: jsonHeaders,
      data: { [fileField.name]: [upload] },
    }),
    "row creation with file field",
  );
  expect(JSON.stringify(row), `row response must reference the uploaded file ${marker}`).toContain(marker);
}

test("seaweedfs: an uploaded Baserow file-field document is stored in the SeaweedFS bucket", async ({ page, browser }) => {
  skipUnlessServiceEnabled("seaweedfs");
  skipUnlessServiceEnabled("sso");
  test.setTimeout(180_000);

  const baseUrl = normalizeBaseUrl(process.env.BASEROW_BASE_URL || "");
  const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
  const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");

  await runSeaweedfsStorageCheck(page, browser, {
    label: "a Baserow file-field upload",
    action: async (appPage) => {
      expect(baseUrl, "BASEROW_BASE_URL must be set").toBeTruthy();
      expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
      expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();

      const session = await getBaserowSession(appPage, baseUrl.replace(/\/$/, ""), adminUsername, adminPassword);
      await createBaserowFileRow(appPage, baseUrl.replace(/\/$/, ""), session.access_token);
    },
  });
});
