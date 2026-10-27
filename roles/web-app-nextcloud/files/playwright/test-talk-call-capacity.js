const { test, expect } = require("@playwright/test");
const { resolveTimeout, isOnionTarget } = require("./timeouts");
const { decodeDotenvQuotedValue, gotoOnion } = require("./personas");

const talkEnabled = decodeDotenvQuotedValue(process.env.NEXTCLOUD_TALK_SETTINGS_CHECK_ENABLED) === "true";
const callParticipants = 6;
const ocsHeaders = { "OCS-APIRequest": "true", Accept: "application/json" };
const joinCallPattern = /^(join call|start call|anruf beitreten|anruf starten)$/i;
const leaveCallPattern = /^(leave call|anruf verlassen)$/i;
const displayNamePattern = /display name|anzeigename/i;
const turnQuotaReachedCode = 486;

function trackPeerConnections() {
  const Original = window.RTCPeerConnection;
  const stats = { connections: [], iceErrorCodes: [] };
  window.__talkCallStats = stats;
  function Tracked(...args) {
    const connection = new Original(...args);
    stats.connections.push(connection);
    connection.addEventListener("icecandidateerror", (event) => stats.iceErrorCodes.push(event.errorCode));
    return connection;
  }
  Tracked.prototype = Original.prototype;
  Object.setPrototypeOf(Tracked, Original);
  window.RTCPeerConnection = Tracked;
}

function readCallStats(page) {
  return page.evaluate(() => {
    const stats = window.__talkCallStats;
    return {
      connected: stats.connections.filter((connection) => connection.connectionState === "connected").length,
      iceErrorCodes: stats.iceErrorCodes,
    };
  });
}

async function createPublicRoom(page, baseUrl) {
  const response = await page.request.post(`${baseUrl}/ocs/v2.php/apps/spreed/api/v4/room`, {
    headers: ocsHeaders,
    data: { roomType: 3, roomName: `Playwright call capacity ${Date.now()}` },
  });
  expect(response.ok(), `creating the public Talk room answered HTTP ${response.status()}`).toBeTruthy();
  return (await response.json()).ocs.data.token;
}

async function joinCallAsGuest(browser, roomUrl, name) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true, permissions: ["camera", "microphone"] });
  await context.addInitScript(trackPeerConnections);
  const page = await context.newPage();
  await gotoOnion(page, roomUrl, { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) });
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel(displayNamePattern).first().fill(name, { timeout: resolveTimeout(60_000) });
  const joinButton = dialog.getByRole("button", { name: joinCallPattern }).last();
  await expect(joinButton, `${name}: the join button stays disabled after the display name`).toBeEnabled({
    timeout: resolveTimeout(30_000),
  });
  await joinButton.click({ timeout: resolveTimeout(30_000) });
  await expect(page.getByRole("button", { name: leaveCallPattern }).first(), `${name} never entered the call`).toBeVisible({
    timeout: resolveTimeout(60_000),
  });
  return { name, page, context };
}

exports.register = function (shared) {
  test("nextcloud talk call holds more than five participants", async ({ browser }) => {
    test.skip(!talkEnabled, "Talk is disabled in the current Playwright env");
    test.skip(isOnionTarget(), "Nextcloud Talk realtime (HPB signaling + STUN/TURN) is WebRTC; not reachable over Tor");
    test.setTimeout(resolveTimeout(15 * 60_000));

    const baseUrl = shared.env.nextcloudBaseUrl;
    const adminContext = await browser.newContext({ ignoreHTTPSErrors: true });
    const adminPage = await adminContext.newPage();
    const guests = [];
    let token = "";

    try {
      await shared.loginToStandaloneNextcloud(adminPage);
      token = await createPublicRoom(adminPage, baseUrl);

      for (let index = 1; index <= callParticipants; index += 1) {
        guests.push(await joinCallAsGuest(browser, `${baseUrl}/call/${token}`, `Playwright guest ${index}`));
      }

      for (const guest of guests) {
        await expect
          .poll(async () => (await readCallStats(guest.page)).connected, {
            timeout: resolveTimeout(120_000),
            message: `${guest.name} must hold a connected peer connection to every participant of the ${callParticipants}-person call`,
          })
          .toBeGreaterThanOrEqual(callParticipants);
        expect(
          (await readCallStats(guest.page)).iceErrorCodes,
          `${guest.name}: TURN answered ${turnQuotaReachedCode} Allocation Quota Reached`,
        ).not.toContain(turnQuotaReachedCode);
      }
    } finally {
      for (const guest of guests) {
        await guest.context.close().catch(() => {});
      }
      if (token) {
        await adminPage.request
          .delete(`${baseUrl}/ocs/v2.php/apps/spreed/api/v4/room/${token}`, { headers: ocsHeaders })
          .catch(() => {});
      }
      await adminContext.close().catch(() => {});
    }
  });
};
