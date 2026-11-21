const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("administrator: connects the local Pixelfed account through the OOB code flow and publishes an image to it", async ({ page }) => {
    shared.skipUnlessServiceEnabled("pixelfed");
    shared.skipOnOnionSibling("pixelfed");
    test.setTimeout(resolveTimeout(300_000)); // Pixelfed sign-in, OAuth approval, media upload and the publishing worker round-trip
    const label = "break-glass administrator";
    const marker = `openpost-e2e-pixelfed ${Date.now()}`;

    await shared.signInViaLocal(page, shared.env.breakglassEmail, shared.env.breakglassPassword, label);
    await shared.connectPixelfedAccount(page, label);
    const headers = shared.apiSession();
    const target = await shared.apiAccount(page, headers, "pixelfed");
    const rendition = await shared.apiPublishImage(page, headers, target, marker, label);
    expect(rendition.external_url, `${label}: OpenPost must record the URL of the Pixelfed post`).toBeTruthy();
    await expect
      .poll(async () => (await page.request.get(rendition.external_url)).status(), {
        timeout: resolveTimeout(60_000),
        message: `${label}: expected the Pixelfed post at ${rendition.external_url}`,
      })
      .toBe(200);
    await shared.logout(page, label);
  });
};
