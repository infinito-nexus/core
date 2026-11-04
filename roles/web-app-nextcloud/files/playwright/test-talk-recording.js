const { test, expect, chromium } = require("@playwright/test");
const { resolveTimeout, isOnionTarget } = require("./timeouts");
const { decodeDotenvQuotedValue } = require("./personas");
const { ocsHeaders, createPublicRoom, joinCallAsGuest } = require("./test-talk-call-capacity");

const talkEnabled = decodeDotenvQuotedValue(process.env.NEXTCLOUD_TALK_SETTINGS_CHECK_ENABLED) === "true";
const recordingAudio = 2;
const recordingFailed = 5;
const recordingDurationMs = 15_000;

async function ocs(page, method, url) {
  const response = await page.request.fetch(url, { method, headers: ocsHeaders });
  const body = await response.json().catch(() => ({}));
  return { status: response.status(), data: body?.ocs?.data };
}

async function readCallRecording(page, baseUrl, token) {
  const { data } = await ocs(page, "GET", new URL(`ocs/v2.php/apps/spreed/api/v4/room/${token}`, baseUrl).toString());
  return data?.callRecording;
}

async function findStoredRecording(page, baseUrl, token) {
  const { data } = await ocs(page, "GET", new URL("ocs/v2.php/apps/notifications/api/v2/notifications", baseUrl).toString());
  const stored = (Array.isArray(data) ? data : []).find(
    (notification) =>
      notification.app === "spreed" &&
      notification.object_type === "recording" &&
      notification.object_id === token &&
      notification.messageRichParameters?.file?.path,
  );
  return stored ? stored.messageRichParameters.file : null;
}

function readFileSize(page, path) {
  return page.evaluate(async (relativePath) => {
    const user = window.OC.getCurrentUser().uid;
    const encoded = relativePath.split("/").filter(Boolean).map(encodeURIComponent).join("/");
    const response = await fetch(`${window.OC.getRootPath()}/remote.php/dav/files/${encodeURIComponent(user)}/${encoded}`, {
      method: "PROPFIND",
      headers: { Depth: "0", requesttoken: window.OC.requestToken, "Content-Type": "application/xml" },
      body: '<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:getcontentlength/></d:prop></d:propfind>',
    });
    if (response.status !== 207) {
      return -response.status;
    }
    const length = new DOMParser()
      .parseFromString(await response.text(), "application/xml")
      .getElementsByTagNameNS("DAV:", "getcontentlength")[0];
    return length ? Number(length.textContent) : 0;
  }, path);
}

exports.register = function (shared) {
  test("nextcloud talk recording server stores a recording of a call", async ({ browser }) => {
    test.skip(!talkEnabled, "Talk is disabled in the current Playwright env");
    test.skip(isOnionTarget(), "Nextcloud Talk realtime (HPB signaling + recording) is WebRTC; not reachable over Tor");
    test.setTimeout(resolveTimeout(10 * 60_000));

    const baseUrl = shared.env.nextcloudBaseUrl;
    const adminContext = await browser.newContext({ ignoreHTTPSErrors: true });
    const adminPage = await adminContext.newPage();
    const mediaBrowser = await chromium.launch({
      args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
    });
    let token = "";

    try {
      await shared.loginToStandaloneNextcloud(adminPage);
      token = await createPublicRoom(adminPage, baseUrl);
      await joinCallAsGuest(mediaBrowser, new URL(`call/${token}`, baseUrl).toString(), "Playwright recording guest");

      const recordingUrl = new URL(`ocs/v2.php/apps/spreed/api/v1/recording/${token}`, baseUrl).toString();
      const start = await adminPage.request.post(recordingUrl, { headers: ocsHeaders, data: { status: recordingAudio } });
      expect(start.ok(), `starting the call recording answered HTTP ${start.status()}: ${await start.text()}`).toBeTruthy();

      await expect
        .poll(async () => readCallRecording(adminPage, baseUrl, token), {
          timeout: resolveTimeout(180_000),
          message: "the recording server must join the call and report the audio recording as running",
        })
        .toBe(recordingAudio);

      await adminPage.waitForTimeout(recordingDurationMs);

      const stop = await ocs(adminPage, "DELETE", recordingUrl);
      expect(stop.status, "stopping the call recording must succeed").toBe(200);
      expect(await readCallRecording(adminPage, baseUrl, token), "the recording must not end as failed").not.toBe(recordingFailed);

      let stored = null;
      await expect
        .poll(
          async () => {
            stored = await findStoredRecording(adminPage, baseUrl, token);
            return Boolean(stored);
          },
          {
            timeout: resolveTimeout(300_000),
            message: "the recording server must upload the recording and Talk must notify the moderator that it is stored",
          },
        )
        .toBe(true);

      await adminPage.goto(new URL("apps/files/", baseUrl).toString(), { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) });
      expect(await readFileSize(adminPage, stored.path), `the stored recording ${stored.path} must not be empty`).toBeGreaterThan(0);
    } finally {
      await mediaBrowser.close().catch(() => {});
      if (token) {
        await adminPage.request
          .delete(new URL(`ocs/v2.php/apps/spreed/api/v4/room/${token}`, baseUrl).toString(), { headers: ocsHeaders })
          .catch(() => {});
      }
      await adminContext.close().catch(() => {});
    }
  });
};
