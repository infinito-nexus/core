const { test, expect, chromium } = require("@playwright/test");
const { resolveTimeout, isOnionTarget } = require("./timeouts");
const { decodeDotenvQuotedValue, gotoOnion } = require("./personas");

const talkEnabled = decodeDotenvQuotedValue(process.env.NEXTCLOUD_TALK_SETTINGS_CHECK_ENABLED) === "true";
const directMediaEnabled = decodeDotenvQuotedValue(process.env.NEXTCLOUD_TALK_DIRECT_MEDIA_ENABLED) === "true";
const directMediaAddress = decodeDotenvQuotedValue(process.env.NEXTCLOUD_TALK_DIRECT_MEDIA_ADDRESS);
const directMediaPortStart = Number(decodeDotenvQuotedValue(process.env.NEXTCLOUD_TALK_DIRECT_MEDIA_PORT_START));
const directMediaPortEnd = Number(decodeDotenvQuotedValue(process.env.NEXTCLOUD_TALK_DIRECT_MEDIA_PORT_END));
const callParticipants = 6;
const ocsHeaders = { "OCS-APIRequest": "true", Accept: "application/json" };
const joinCallPattern = /^(join call|start call|anruf beitreten|anruf starten)$/i;
const leaveCallPattern = /^(leave call|anruf verlassen)$/i;
const guestNamePattern = /enter your name|display name|anzeigename/i;
const submitGuestNamePattern = /submit name and join/i;
const turnQuotaReachedCode = 486;

function trackPeerConnections() {
  const Original = window.RTCPeerConnection;
  const stats = { connections: [], iceErrorCodes: [] };
  stats.selectedPairs = async () => {
    const pairs = [];
    for (const connection of stats.connections) {
      if (connection.connectionState !== "connected") {
        continue;
      }
      const entries = new Map();
      (await connection.getStats()).forEach((entry) => entries.set(entry.id, entry));
      const selectedIds = [...entries.values()]
        .filter((entry) => entry.type === "transport" && entry.selectedCandidatePairId)
        .map((entry) => entry.selectedCandidatePairId);
      for (const id of selectedIds) {
        const pair = entries.get(id);
        const local = pair && entries.get(pair.localCandidateId);
        const remote = pair && entries.get(pair.remoteCandidateId);
        if (local && remote) {
          pairs.push({
            localType: local.candidateType,
            remoteType: remote.candidateType,
            remoteAddress: remote.address || remote.ip,
            remotePort: remote.port,
          });
        }
      }
    }
    return pairs;
  };
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

function isDirectPair(pair) {
  return (
    pair.localType !== "relay" &&
    pair.remoteType !== "relay" &&
    pair.remoteAddress === directMediaAddress &&
    pair.remotePort >= directMediaPortStart &&
    pair.remotePort <= directMediaPortEnd
  );
}

function readSelectedPairs(page) {
  return page.evaluate(() => window.__talkCallStats.selectedPairs());
}

async function createPublicRoom(page, baseUrl) {
  const response = await page.request.post(new URL("ocs/v2.php/apps/spreed/api/v4/room", baseUrl).toString(), {
    headers: ocsHeaders,
    data: { roomType: 3, roomName: `Playwright call capacity ${Date.now()}` },
  });
  expect(response.ok(), `creating the public Talk room answered HTTP ${response.status()}`).toBeTruthy();
  return (await response.json()).ocs.data.token;
}

async function joinCallAsGuest(browser, roomUrl, name) {
  // Talk flags a HeadlessChrome user agent as unsupported, and that error toast covers the call button.
  const userAgent = `Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${browser.version()} Safari/537.36`;
  const context = await browser.newContext({ ignoreHTTPSErrors: true, permissions: ["camera", "microphone"], userAgent });
  await context.addInitScript(trackPeerConnections);
  const page = await context.newPage();
  await gotoOnion(page, roomUrl, { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) });
  const dialog = page.getByRole("dialog");
  const submitName = dialog.getByRole("button", { name: submitGuestNamePattern });
  const dialogJoin = dialog.getByRole("button", { name: joinCallPattern }).last();
  const leaveButton = page.getByRole("button", { name: leaveCallPattern }).first();
  await dialog.getByRole("textbox", { name: guestNamePattern }).fill(name, { timeout: resolveTimeout(60_000) });
  await expect(submitName.or(dialogJoin).first(), `${name}: the name dialog offers neither submit nor join`).toBeVisible({
    timeout: resolveTimeout(30_000),
  });
  if (await submitName.isVisible()) {
    await submitName.click({ timeout: resolveTimeout(30_000) });
    await page.getByRole("button", { name: joinCallPattern }).first().click({ timeout: resolveTimeout(60_000) });
    await expect(leaveButton.or(dialogJoin).first(), `${name}: neither the call nor its device check opened`).toBeVisible({
      timeout: resolveTimeout(60_000),
    });
  }
  if (await dialogJoin.isVisible()) {
    await dialogJoin.click({ timeout: resolveTimeout(30_000) });
  }
  await expect(leaveButton, `${name} never entered the call`).toBeVisible({ timeout: resolveTimeout(60_000) });
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
    const mediaBrowser = await chromium.launch({
      args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
    });
    const guests = [];
    let token = "";

    try {
      await shared.loginToStandaloneNextcloud(adminPage);
      token = await createPublicRoom(adminPage, baseUrl);

      for (let index = 1; index <= callParticipants; index += 1) {
        guests.push(await joinCallAsGuest(mediaBrowser, new URL(`call/${token}`, baseUrl).toString(), `Playwright guest ${index}`));
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
        if (directMediaEnabled) {
          await expect
            .poll(
              async () => {
                const pairs = await readSelectedPairs(guest.page);
                return pairs.some(isDirectPair) ? "direct" : JSON.stringify(pairs);
              },
              {
                timeout: resolveTimeout(60_000),
                message: `${guest.name} must carry media to Janus on ${directMediaAddress}:${directMediaPortStart}-${directMediaPortEnd} without a TURN relay`,
              },
            )
            .toBe("direct");
        }
      }
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
