/**
 * SeaweedFS object-store verification shared by every seaweedfs-consumer spec.
 *
 * A consumer role's `files/playwright/test-seaweedfs.js` provides an
 * app-specific `action(page)` that logs into the application and triggers a
 * real upload (a file, an avatar, a media post, …). With S3 primary storage
 * that upload lands as one or more new objects in the consumer's bucket.
 * `runSeaweedfsStorageCheck` then proves the write reached SeaweedFS:
 *
 *   1. List the consumer's bucket over the S3 API, signed with that
 *      consumer's own identity.
 *   2. Run the app-specific `action(page)`.
 *   3. Re-list and assert the bucket grew — the uploaded document is now
 *      stored in SeaweedFS for that app.
 *
 * The listing goes to the storage engine directly (roles/web-svc-seaweedfs),
 * not to the Filer UI: the Filer moved to roles/web-app-seaweedfs-console,
 * which a node may legitimately not deploy. Signing with the consumer's own
 * access key rather than the administrator's additionally proves that the
 * per-consumer identity in the engine's s3.json reaches its own bucket.
 *
 * Inputs come from the consumer's rendered `templates/playwright.env.j2`
 * (dedicated keys so the check never depends on a role's own login-var
 * naming): SEAWEEDFS_S3_URL, SEAWEEDFS_REGION, SEAWEEDFS_APP_BUCKET,
 * SEAWEEDFS_APP_ACCESS_KEY, SEAWEEDFS_APP_SECRET_KEY.
 */

const { expect } = require("@playwright/test");
const { resolveTimeout } = require("../../timeouts");
const { listObjects } = require("./s3");
const { decodeDotenvQuotedValue, normalizeBaseUrl } = require("./dotenv");

function seaweedfsEnv() {
  return {
    s3Url: normalizeBaseUrl(process.env.SEAWEEDFS_S3_URL || ""),
    region: decodeDotenvQuotedValue(process.env.SEAWEEDFS_REGION || ""),
    bucket: decodeDotenvQuotedValue(process.env.SEAWEEDFS_APP_BUCKET || ""),
    accessKey: decodeDotenvQuotedValue(process.env.SEAWEEDFS_APP_ACCESS_KEY || ""),
    secretKey: decodeDotenvQuotedValue(process.env.SEAWEEDFS_APP_SECRET_KEY || ""),
  };
}

async function collectBucketObjects(request, env) {
  return listObjects(request, {
    baseUrl: env.s3Url,
    bucket: env.bucket,
    region: env.region,
    accessKey: env.accessKey,
    secretKey: env.secretKey,
  });
}

async function runSeaweedfsStorageCheck(page, browser, { action, label = "the application upload", overrides = {}, pollDeadlineMs = 60_000, expectInPlaceOverwrite = false } = {}) {
  const env = { ...seaweedfsEnv(), ...overrides };
  expect(env.s3Url, "SEAWEEDFS_S3_URL must be set").toBeTruthy();
  expect(env.region, "SEAWEEDFS_REGION must be set").toBeTruthy();
  expect(env.bucket, "SEAWEEDFS_APP_BUCKET must be set").toBeTruthy();
  expect(env.accessKey, "SEAWEEDFS_APP_ACCESS_KEY must be set").toBeTruthy();
  expect(env.secretKey, "SEAWEEDFS_APP_SECRET_KEY must be set").toBeTruthy();
  expect(typeof action, "runSeaweedfsStorageCheck requires an `action(page)` callback").toBe("function");

  const before = await collectBucketObjects(page.request, env);

  await action(page);

  // Default: require a NEW object key. This stays immune to background
  // workers (PeerTube transcode, Pixelfed media jobs) that rewrite EXISTING
  // objects during the poll window. Single-slot consumers that overwrite one
  // fixed key in place (e.g. a tenant logo) opt in via expectInPlaceOverwrite
  // to also accept a changed ETag on an existing key.
  const deadline = Date.now() + pollDeadlineMs;
  let after = before;
  let newObjects = [];
  for (;;) {
    after = await collectBucketObjects(page.request, env);
    newObjects = [...after.keys()].filter(
      (key) =>
        !before.has(key) ||
        (expectInPlaceOverwrite && before.get(key) !== after.get(key)),
    );
    if (newObjects.length > 0 || Date.now() >= deadline) {
      break;
    }
    await page.waitForTimeout(resolveTimeout(2_000));
  }

  expect(
    newObjects.length,
    `${label} must write at least one ${expectInPlaceOverwrite ? "new or changed" : "new"} object to the SeaweedFS bucket '${env.bucket}' ` +
      `(objects before: ${before.size}, after: ${after.size}, matched: ${newObjects.length})`,
  ).toBeGreaterThan(0);
}

module.exports = {
  runSeaweedfsStorageCheck,
  collectBucketObjects,
  seaweedfsEnv,
};
