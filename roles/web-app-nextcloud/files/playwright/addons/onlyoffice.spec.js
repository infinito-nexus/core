const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");
const { gotoOnion } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

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
        buffer: Buffer.from(shared.MINIMAL_DOCX_BASE64, "base64"),
      });

    const docBasename = docName.replace(/\.docx$/, "");
    const uploadedRow = page.getByText(docBasename, { exact: false }).first();
    await expect(
      uploadedRow,
      `the uploaded document '${docName}' must appear in the Files listing before it can be opened in ONLYOFFICE`,
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    await shared.dismissBlockingNextcloudModals(page, page);
    await uploadedRow.click();

    const connectorIframe = page.locator("iframe#onlyofficeFrame").first();
    await expect(
      connectorIframe,
      "opening the .docx must mount the onlyoffice connector iframe (#onlyofficeFrame) into the Files view",
    ).toBeVisible({ timeout: resolveTimeout(90_000) });

    const frameUrlMatching = (predicate) => {
      const frame = page.frames().find((candidate) => {
        try {
          return predicate(new URL(candidate.url()));
        } catch {
          return false;
        }
      });
      return frame ? frame.url() : "";
    };

    await expect
      .poll(
        () =>
          frameUrlMatching(
            (url) =>
              url.host === nextcloudHost &&
              /^\/apps\/onlyoffice\/\d+$/.test(url.pathname) &&
              url.searchParams.get("inframe") === "true",
          ),
        {
          message: `the connector iframe must load the onlyoffice editor view '/apps/onlyoffice/<fileid>?inframe=true' from Nextcloud ('${nextcloudHost}'), which is what hands the document over to the document server`,
          timeout: resolveTimeout(90_000),
        },
      )
      .toBeTruthy();

    await expect
      .poll(
        () =>
          frameUrlMatching(
            (url) => url.host === documentServerHost && url.pathname.includes("/web-apps/apps/documenteditor/"),
          ),
        {
          message: `the connector view must embed the document editor served by the web-svc-onlyoffice partner host '${documentServerHost}' (the DocumentServerUrl coupling), not by Nextcloud ('${nextcloudHost}')`,
          timeout: resolveTimeout(120_000),
        },
      )
      .toBeTruthy();

    const editorFrame = page
      .frameLocator("iframe#onlyofficeFrame")
      .frameLocator("iframe[name='frameEditor']");

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
