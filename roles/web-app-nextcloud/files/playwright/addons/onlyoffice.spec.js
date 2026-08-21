const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");
const { gotoOnion } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const MINIMAL_DOCX_BASE64 =
  "UEsDBBQAAAAIAEq201x5bjPX6AAAAK0BAAATAAAAW0NvbnRlbnRfVHlwZXNdLnhtbH1QyU7DMBD9FWuuKHHggBCK0wPLETiUDxjZk8SqN3nc0v49Tlt6QIXjzFv1+tXeO7GjzDYGBbdtB4KCjsaGScHn+rV5AMEFg0EXAyk4EMNq6NeHRCyqNrCCuZT0KCXrmTxyGxOFiowxeyz1zJNMqDc4kbzrunupYygUSlMWDxj6Zxpx64p42df3qUcmxyCeTsQlSwGm5KzGUnG5C+ZXSnNOaKvyyOHZJr6pBJBXExbk74Cz7r0Ok60h8YG5vKGvLPkVs5Em6q2vyvZ/mys94zhaTRf94pZy1MRcF/euvSAebfjpL49zD99QSwMECgAAAAAASrbTXAAAAAAAAAAAAAAAAAYAAABfcmVscy9QSwMEFAAAAAgASrbTXJv9N+qtAAAAKQEAAAsAAABfcmVscy8ucmVsc43POw7CMAwG4KtE3mlaBoRQ0y4IqSsqB7ASN61oHkrCo7cnAwNFDIy2f3+W6/ZpZnanECdnBVRFCYysdGqyWsClP232wGJCq3B2lgQsFKFt6jPNmPJKHCcfWTZsFDCm5A+cRzmSwVg4TzZPBhcMplwGzT3KK2ri27Lc8fBpwNpknRIQOlUB6xdP/9huGCZJRydvhmz6ceIrkWUMmpKAhwuKq3e7yCzwpuarF5sXUEsDBAoAAAAAAEq201wAAAAAAAAAAAAAAAAFAAAAd29yZC9QSwMEFAAAAAgASrbTXC5rweurAAAA6wAAABEAAAB3b3JkL2RvY3VtZW50LnhtbEWOQQ7CIBBFr0LYW6oLY5q27jyBHgBhaIkwQ4Bae3uhLty8n8lM3p/++vGOvSEmSzjwY9NyBqhIW5wG/rjfDhfOUpaopSOEgW+Q+HXs106TWjxgZkWAqVsHPuccOiGSmsHL1FAALDtD0ctcxjiJlaIOkRSkVPzeiVPbnoWXFnlVPklvNUNFrMijRWPRZmKEbiNjrAKmaAmuCFhpUq9e1LvKuDPs/LnE/8/xC1BLAQIeAxQAAAAIAEq201x5bjPX6AAAAK0BAAATAAAAAAAAAAEAAACkgQAAAABbQ29udGVudF9UeXBlc10ueG1sUEsBAh4DCgAAAAAASrbTXAAAAAAAAAAAAAAAAAYAAAAAAAAAAAAQAO1BGQEAAF9yZWxzL1BLAQIeAxQAAAAIAEq201yb/TfqrQAAACkBAAALAAAAAAAAAAEAAACkgT0BAABfcmVscy8ucmVsc1BLAQIeAwoAAAAAAEq201wAAAAAAAAAAAAAAAAFAAAAAAAAAAAAEADtQRMCAAB3b3JkL1BLAQIeAxQAAAAIAEq201wua8HrqwAAAOsAAAARAAAAAAAAAAEAAACkgTYCAAB3b3JkL2RvY3VtZW50LnhtbFBLBQYAAAAABQAFACABAAAQAwAAAAA=";

test("onlyoffice addon: opening a document loads the partner document-server editor", async ({ browser }) => {
  skipUnlessAddonEnabled("onlyoffice");
  test.setTimeout(resolveTimeout(180_000));

  const unquote = (v) => ((v || "").trim().replace(/^"(.*)"$/, "$1"));
  const expectedDsUrl = unquote(process.env.NEXTCLOUD_ONLYOFFICE_EXPECTED_DOCUMENT_SERVER_URL);
  expect(
    expectedDsUrl,
    "NEXTCLOUD_ONLYOFFICE_EXPECTED_DOCUMENT_SERVER_URL must be rendered into the Playwright env so the spec can prove the editor iframe is served by the real web-svc-onlyoffice partner host",
  ).toBeTruthy();
  const documentServerHost = new URL(expectedDsUrl).host;
  const nextcloudHost = new URL(shared.env.nextcloudBaseUrl).host;

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    const filesUrl = new URL("apps/files/", shared.env.nextcloudBaseUrl).toString();
    await gotoOnion(page, filesUrl, { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) });
    await shared.dismissBlockingNextcloudModals(page, page);

    const docName = `infinito-onlyoffice-${Date.now()}.docx`;
    await page
      .locator('input[type="file"]')
      .first()
      .setInputFiles({
        name: docName,
        mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        buffer: Buffer.from(MINIMAL_DOCX_BASE64, "base64"),
      });

    const docBasename = docName.replace(/\.docx$/, "");
    const uploadedRow = page.getByText(docBasename, { exact: false }).first();
    await expect(
      uploadedRow,
      `the uploaded document '${docName}' must appear in the Files listing before it can be opened in ONLYOFFICE`,
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    await shared.dismissBlockingNextcloudModals(page, page);
    await uploadedRow.click();

    const editorIframeElement = page.locator(
      "iframe#iframeEditor, iframe[name='frameEditor'], iframe[src*='/web-apps/'], iframe[src*='OfficeWeb']",
    ).first();
    await expect(
      editorIframeElement,
      "opening the .docx must mount the ONLYOFFICE editor iframe (the onlyoffice connector view), proving the partner document server was reached",
    ).toBeVisible({ timeout: resolveTimeout(90_000) });

    const editorSrc = (await editorIframeElement.getAttribute("src").catch(() => "")) || "";
    let editorSrcHost = "";
    try {
      editorSrcHost = new URL(editorSrc, shared.env.nextcloudBaseUrl).host;
    } catch {
      editorSrcHost = "";
    }
    expect(
      editorSrcHost,
      `the ONLYOFFICE editor iframe must be served by the web-svc-onlyoffice partner host '${documentServerHost}' (the DocumentServerUrl coupling), not by Nextcloud ('${nextcloudHost}'); got src '${editorSrc}'`,
    ).toBe(documentServerHost);

    const editorFrame = page.frameLocator(
      "iframe#iframeEditor, iframe[name='frameEditor'], iframe[src*='/web-apps/'], iframe[src*='OfficeWeb']",
    );

    const jwtError = editorFrame.getByText(
      /security token is not correctly formed|token is not valid|invalid token|error while downloading|download failed/i,
    );
    await expect(
      jwtError,
      "the ONLYOFFICE editor must not show a JWT/security-token or download error: that means the shared jwt_secret coupling or the document-server <-> Nextcloud round trip is broken",
    ).toHaveCount(0, { timeout: resolveTimeout(90_000) });

    const editorSurface = editorFrame.locator(
      "#editor_sdk, #id_main_view, .asc-window, canvas, #toolbar, .toolbar",
    ).first();
    await expect(
      editorSurface,
      "the ONLYOFFICE editor surface (toolbar/canvas) must render inside the partner iframe, proving the full JWT-authenticated document-server round trip works end to end",
    ).toBeVisible({ timeout: resolveTimeout(120_000) });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
