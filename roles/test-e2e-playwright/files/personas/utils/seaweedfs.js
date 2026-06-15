/**
 * SeaweedFS object-store verification shared by every seaweedfs-consumer spec.
 *
 * A consumer role's `files/playwright/test-seaweedfs.js` provides an
 * app-specific `action(page)` that logs into the application and triggers a
 * real upload (a file, an avatar, a media post, …). With S3 primary storage
 * that upload lands as one or more new objects in the consumer's bucket.
 * `runSeaweedfsStorageCheck` then proves the write reached SeaweedFS:
 *
 *   1. Count the objects already in the consumer's bucket through the
 *      oauth2-gated Filer UI (administrator session, isolated context).
 *   2. Run the app-specific `action(page)` in the test's own browser context
 *      so the application's user session never collides with the admin one.
 *   3. Re-count through the Filer UI and assert the bucket grew — the
 *      uploaded document is now stored in SeaweedFS for that app.
 *
 * The Filer UI count is read from the Filer's own JSON listing (the endpoint
 * the UI renders), walked recursively so a write into any prefix is seen,
 * regardless of how the application namespaces its objects.
 *
 * Inputs come from the consumer's rendered `templates/playwright.env.j2`
 * (dedicated keys so the check never depends on a role's own login-var
 * naming): SEAWEEDFS_FILER_URL, SEAWEEDFS_APP_BUCKET,
 * SEAWEEDFS_ADMIN_USERNAME, SEAWEEDFS_ADMIN_PASSWORD.
 */

const { expect } = require("@playwright/test");
const { performKeycloakLoginForm } = require("./keycloak");
const { decodeDotenvQuotedValue, normalizeBaseUrl } = require("./dotenv");

const DIR_MODE_BIT = 0x80000000;
const LISTING_PAGE_LIMIT = 10_000;
const WALK_BUDGET = 4_000;

function isAuthChain(url) {
  return /\/oauth2\/|\/realms\/|\/protocol\/openid-connect\//.test(url || "");
}

function seaweedfsEnv() {
  return {
    filerUrl: normalizeBaseUrl(process.env.SEAWEEDFS_FILER_URL || ""),
    bucket: decodeDotenvQuotedValue(process.env.SEAWEEDFS_APP_BUCKET || ""),
    adminUsername: decodeDotenvQuotedValue(process.env.SEAWEEDFS_ADMIN_USERNAME || ""),
    adminPassword: decodeDotenvQuotedValue(process.env.SEAWEEDFS_ADMIN_PASSWORD || ""),
  };
}

async function adminLoginFiler(page, env) {
  // Authenticate at the Filer root: the oauth2-proxy post-login redirect lands
  // on "/", so logging in via a deep path would drop us back at the root.
  await page.goto(env.filerUrl, { waitUntil: "domcontentloaded" });
  if (isAuthChain(page.url())) {
    await performKeycloakLoginForm(page, env.adminUsername, env.adminPassword);
    await page.waitForLoadState("networkidle").catch(() => {});
  }
  expect(
    isAuthChain(page.url()),
    "administrator must reach the SeaweedFS Filer UI without staying in the auth chain",
  ).toBe(false);
}

async function listDirFiles(page, filerUrl, dirPath, files, budget) {
  if (budget.remaining <= 0) {
    return;
  }
  budget.remaining -= 1;

  let lastFileName = "";
  for (;;) {
    const sep = dirPath.includes("?") ? "&" : "?";
    const query = `limit=${LISTING_PAGE_LIMIT}${lastFileName ? `&lastFileName=${encodeURIComponent(lastFileName)}` : ""}`;
    const res = await page.request.get(`${filerUrl}${dirPath}${sep}${query}`, {
      headers: { Accept: "application/json" },
    });
    if (!res.ok()) {
      return;
    }
    const json = await res.json().catch(() => null);
    const entries = json && Array.isArray(json.Entries) ? json.Entries : [];
    for (const entry of entries) {
      const fullPath = entry && entry.FullPath ? String(entry.FullPath) : "";
      if (!fullPath) {
        continue;
      }
      const isDir = (Number(entry.Mode) & DIR_MODE_BIT) !== 0;
      if (isDir) {
        await listDirFiles(page, filerUrl, `${fullPath}/`, files, budget);
      } else {
        files.set(fullPath, String(entry.Mtime || entry.Md5 || ""));
      }
    }
    if (!json || !json.ShouldDisplayLoadMore || !json.LastFileName) {
      return;
    }
    lastFileName = String(json.LastFileName);
  }
}

async function collectBucketObjects(adminPage, env) {
  const files = new Map();
  await listDirFiles(adminPage, env.filerUrl, `/buckets/${env.bucket}/`, files, {
    remaining: WALK_BUDGET,
  });
  return files;
}

async function countBucketObjects(adminPage, env) {
  return (await collectBucketObjects(adminPage, env)).size;
}

async function adminCountBucketObjects(browser, env) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const page = await context.newPage();
    await adminLoginFiler(page, env);
    return await countBucketObjects(page, env);
  } finally {
    await context.close();
  }
}

async function runSeaweedfsStorageCheck(page, browser, { action, label = "the application upload", overrides = {}, pollDeadlineMs = 60_000, expectInPlaceOverwrite = false } = {}) {
  const env = { ...seaweedfsEnv(), ...overrides };
  expect(env.filerUrl, "SEAWEEDFS_FILER_URL must be set").toBeTruthy();
  expect(env.bucket, "SEAWEEDFS_APP_BUCKET must be set").toBeTruthy();
  expect(typeof action, "runSeaweedfsStorageCheck requires an `action(page)` callback").toBe("function");

  // Log the administrator into the Filer once in a dedicated context, then
  // reuse that authenticated session for every object count. Re-authenticating
  // per count (new context + Keycloak round-trip) is slow enough to blow the
  // per-test timeout while polling, so the session is established a single time.
  const adminContext = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const adminPage = await adminContext.newPage();
    await adminLoginFiler(adminPage, env);

    const before = await collectBucketObjects(adminPage, env);

    await action(page);

    // Default: require a NEW object key. This stays immune to background
    // workers (PeerTube transcode, Pixelfed media jobs) that rewrite EXISTING
    // objects during the poll window. Single-slot consumers that overwrite one
    // fixed key in place (e.g. a tenant logo) opt in via expectInPlaceOverwrite
    // to also accept a changed mtime on an existing key.
    const deadline = Date.now() + pollDeadlineMs;
    let after = before;
    let newObjects = [];
    for (;;) {
      after = await collectBucketObjects(adminPage, env);
      newObjects = [...after.keys()].filter(
        (path) =>
          !before.has(path) ||
          (expectInPlaceOverwrite && before.get(path) !== after.get(path)),
      );
      if (newObjects.length > 0 || Date.now() >= deadline) {
        break;
      }
      await page.waitForTimeout(2_000);
    }

    expect(
      newObjects.length,
      `${label} must write at least one ${expectInPlaceOverwrite ? "new or changed" : "new"} object to the SeaweedFS bucket '${env.bucket}' ` +
        `(objects before: ${before.size}, after: ${after.size}, matched: ${newObjects.length})`,
    ).toBeGreaterThan(0);
  } finally {
    await adminContext.close();
  }
}

module.exports = {
  runSeaweedfsStorageCheck,
  adminCountBucketObjects,
  adminLoginFiler,
  seaweedfsEnv,
  isAuthChain,
};
