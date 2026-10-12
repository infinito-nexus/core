const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");
const { gotoOnion } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

test("richdocuments addon: Collabora connector wired to the partner WOPI server", async ({ browser }) => {
  skipUnlessAddonEnabled("richdocuments");
  test.setTimeout(resolveTimeout(120_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    await gotoOnion(page,
      new URL("settings/admin/richdocuments", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) }
    );
    await shared.dismissBlockingNextcloudModals(page, page);

    const adminSection = page
      .locator("#richdocuments, [data-cy='collabora-server-settings']")
      .or(page.getByText(/collabora online/i).first());
    await expect(
      adminSection.first(),
      "the Collabora Online (richdocuments) admin settings section must render, proving the app is enabled"
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    const wopiField = page.locator("input#wopi_url, input[name='wopi_url']").first();
    await expect(
      wopiField,
      "the Collabora server URL (WOPI) field must render in the admin panel"
    ).toBeVisible({ timeout: resolveTimeout(60_000) });
    const wopiValue = ((await wopiField.inputValue().catch(() => "")) || "").trim();
    expect(
      /^https?:\/\/.+/.test(wopiValue),
      "the WOPI server URL must be a real partner URL (config:app:set wopi_url); empty means the partner endpoint was never wired"
    ).toBeTruthy();
    expect(
      new URL(wopiValue).host,
      "the WOPI server URL must point at the partner Collabora host, not Nextcloud itself"
    ).not.toBe(new URL(shared.env.nextcloudBaseUrl).host);

    const connectionError = page.getByText(
      /could not establish connection to the collabora online server|failed to connect|not a valid (collabora|wopi)/i
    );
    await expect(
      connectionError,
      "the Collabora connection-failure banner must be absent: richdocuments must reach the partner WOPI server (config:app:set wopi_url + occ richdocuments:activate-config discovery)"
    ).toHaveCount(0, { timeout: resolveTimeout(30_000) });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});

test("richdocuments addon: opening a document loads it through the partner WOPI server", async ({ browser }) => {
  skipUnlessAddonEnabled("richdocuments");
  test.setTimeout(resolveTimeout(240_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  const editorReplies = [];
  page.on("websocket", (socket) => {
    if (!/\/cool\/(?:.+\/)?ws(?:\?|$)/.test(socket.url())) {
      return;
    }
    socket.on("framereceived", ({ payload }) => {
      const reply = payload.toString().slice(0, 120);
      if (/^(status|error):/.test(reply)) {
        editorReplies.push(reply);
      }
    });
  });

  try {
    await shared.loginToStandaloneNextcloud(page);

    const filesUrl = new URL("apps/files/", shared.env.nextcloudBaseUrl).toString();
    await gotoOnion(page, filesUrl, { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) });
    await shared.dismissBlockingNextcloudModals(page, page);

    const docBasename = `infinito-collabora-${Date.now()}`;
    await page
      .locator('input[type="file"]')
      .first()
      .setInputFiles({
        name: `${docBasename}.docx`,
        mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        buffer: Buffer.from(shared.MINIMAL_DOCX_BASE64, "base64"),
      });

    const uploadedRow = page.getByText(docBasename, { exact: false }).first();
    await expect(
      uploadedRow,
      `the uploaded document '${docBasename}.docx' must appear in the Files listing before it can be opened in Collabora`
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    await shared.dismissBlockingNextcloudModals(page, page);
    await uploadedRow.click();

    await expect
      .poll(() => editorReplies.length, {
        message:
          "opening the document must make Collabora answer on its editor websocket (/cool/ws) with a 'status:' or an 'error:' frame; silence means the browser never reached the editor that the discovery of web-svc-collabora advertises",
        timeout: resolveTimeout(180_000),
      })
      .toBeGreaterThan(0);
    expect(
      editorReplies[0],
      "Collabora must answer the document load with a 'status:' frame; 'error: cmd=internal kind=unauthorized' means it refused the WOPI host (aliasgroup1 of web-svc-collabora) or its CheckFileInfo call to Nextcloud failed, and the Collabora log names which"
    ).toMatch(/^status:/);
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
