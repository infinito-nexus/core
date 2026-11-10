// SeaweedFS object-store scenario for XWiki.
//
// XWiki 18.7 keeps attachment content in a blob store. templates/xwiki.properties.j2 switches
// that store to S3 (store.blobStoreType=s3 plus store.s3.* from the `objstore` lookup, which
// resolves to SeaweedFS when seaweedfs is the enabled engine) once the "S3 Blob Store"
// extension (org.xwiki.commons:xwiki-commons-store-blob-s3) is installed on the root namespace
// by tasks/04_extensions.yml. With that store active, attaching a file to a wiki page writes
// the attachment content into the consumer bucket as a new object.
//
// The action attaches through XWiki's own REST attachment endpoint as the built-in superadmin:
// templates/playwright.env.j2 declares both personas blocked (the administrator page carries no
// password property and the deployment authenticates every privileged call as superadmin), so
// superadmin is the only credential that can drive a write into the attachment store.
//
// Required env (rendered by templates/playwright.env.j2):
//   APP_BASE_URL, XWIKI_SUPERADMIN_USERNAME, XWIKI_SUPERADMIN_PASSWORD and the SEAWEEDFS_* keys
//   consumed by runSeaweedfsStorageCheck.

const { randomUUID } = require("node:crypto");
const { test, expect } = require("@playwright/test");
const { resolveTimeout, isOnionTarget } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { normalizeBaseUrl, requireDotenvValue, runSeaweedfsStorageCheck } = require("./personas");

test.use({ ignoreHTTPSErrors: true });

test("seaweedfs: an attachment added to an XWiki page is stored in the SeaweedFS bucket", async ({ page, browser }) => {
  test.skip(isOnionTarget(), "SeaweedFS S3 API is not a Tor surface on an onion node (headless backend)");
  skipUnlessServiceEnabled("seaweedfs");
  test.setTimeout(resolveTimeout(300_000));

  const appBaseUrl = normalizeBaseUrl(
    requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"),
  );
  const superadminUsername = requireDotenvValue(
    process.env.XWIKI_SUPERADMIN_USERNAME,
    "XWIKI_SUPERADMIN_USERNAME",
  );
  const superadminPassword = requireDotenvValue(
    process.env.XWIKI_SUPERADMIN_PASSWORD,
    "XWIKI_SUPERADMIN_PASSWORD",
  );
  const authorization = `Basic ${Buffer.from(`${superadminUsername}:${superadminPassword}`).toString("base64")}`;

  await runSeaweedfsStorageCheck(page, browser, {
    label: "an XWiki page attachment upload",
    action: async (appPage) => {
      const base = appBaseUrl.replace(/\/$/, "");
      const marker = `infinito-storage-check-${Date.now()}-${randomUUID()}.txt`;
      const pageUrl = `${base}/rest/wikis/xwiki/spaces/Main/pages/WebHome`;

      const session = await appPage.request.get(`${base}/rest/wikis/xwiki/spaces`, {
        headers: { Authorization: authorization },
        timeout: resolveTimeout(60_000),
      });
      expect(
        session.status(),
        `XWiki refused the superadmin REST session with HTTP ${session.status()}; without it no ` +
          "form token exists and the attachment write cannot be attempted",
      ).toBe(200);
      const formToken = session.headers()["xwiki-form-token"];

      const upload = await appPage.request.put(`${pageUrl}/attachments/${marker}`, {
        headers: {
          Authorization: authorization,
          "Content-Type": "application/octet-stream",
          ...(formToken ? { "XWiki-Form-Token": formToken } : {}),
        },
        data: Buffer.from(`infinito storage check ${marker}`),
        timeout: resolveTimeout(120_000),
      });
      expect(
        upload.status(),
        `XWiki rejected the attachment upload with HTTP ${upload.status()}; the wiki write failed ` +
          "rather than the object store",
      ).toBeLessThan(300);

      const listing = await appPage.request.get(`${pageUrl}/attachments`, {
        headers: { Authorization: authorization, Accept: "application/json" },
        timeout: resolveTimeout(60_000),
      });
      expect(
        listing.status(),
        `XWiki did not return the attachment listing for Main.WebHome (HTTP ${listing.status()})`,
      ).toBeLessThan(300);
      expect(
        await listing.text(),
        `XWiki reported the upload of '${marker}' as accepted but does not list it on Main.WebHome`,
      ).toContain(marker);
    },
  });
});
