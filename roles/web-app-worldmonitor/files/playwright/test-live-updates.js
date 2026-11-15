const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { hostnameOf, isOnionUrl } = require("./personas");
const { skipUnlessServiceEnabled, skipUnlessServiceDisabled } = require("./service-gating");

const API_PATH_RE = /^\/api\//;
const GATE_LOCATION_RE = /\/oauth2\/|openid-connect/;
const SOCKET_FAILURE_RE = /WebSocket connection to '([^']+)' failed/;
const TRANSPORT_FAILURE_RE = /net::ERR_(?!ABORTED)/;

function proxyRefusal(status, headers) {
  if (status >= 300 && status < 400) return GATE_LOCATION_RE.test(headers.location || "");
  return status >= 400 && /^text\/html/i.test(headers["content-type"] || "");
}

function failedTransport(text, url, host) {
  const socket = SOCKET_FAILURE_RE.exec(text);
  if (socket) return hostnameOf(socket[1]) === host;
  return TRANSPORT_FAILURE_RE.test(text) && hostnameOf(url) === host;
}

function recordLiveTraffic(page, host) {
  const traffic = { pending: new Set(), answered: [], refused: [], failed: [], streams: [], consoleErrors: [] };
  const onHost = (request) => hostnameOf(request.url()) === host;
  const isApi = (request) => onHost(request) && API_PATH_RE.test(new URL(request.url()).pathname);

  page.on("request", (request) => {
    if (isApi(request)) traffic.pending.add(request);
  });
  page.on("requestfinished", (request) => traffic.pending.delete(request));
  page.on("requestfailed", (request) => {
    traffic.pending.delete(request);
    const { errorText } = request.failure() || { errorText: "" };
    if (onHost(request) && TRANSPORT_FAILURE_RE.test(errorText)) traffic.failed.push(`${request.url()}: ${errorText}`);
  });
  page.on("response", (response) => {
    const request = response.request();
    const headers = response.headers();
    const entry = `${response.status()} ${request.url()}`;
    if (request.resourceType() === "eventsource" && onHost(request)) {
      if (response.status() !== 200 || !/^text\/event-stream/i.test(headers["content-type"] || "")) {
        traffic.streams.push(entry);
      }
    }
    if (!isApi(request)) return;
    if (proxyRefusal(response.status(), headers)) traffic.refused.push(entry);
    else if (response.status() < 400) traffic.answered.push(entry);
  });
  page.on("websocket", (socket) => {
    if (hostnameOf(socket.url()) !== host) return;
    socket.on("socketerror", (error) => traffic.failed.push(`${socket.url()}: ${error}`));
  });
  page.on("console", (message) => {
    if (message.type() === "error" && failedTransport(message.text(), message.location().url, host)) {
      traffic.consoleErrors.push(message.text());
    }
  });
  return traffic;
}

async function expectLiveTraffic(page, shared, openDashboard) {
  const traffic = recordLiveTraffic(page, hostnameOf(shared.env.appBaseUrl));
  await openDashboard();

  await expect
    .poll(() => traffic.answered.length, {
      timeout: resolveTimeout(60_000),
      message: "the dashboard must fetch live data from /api through the proxy",
    })
    .toBeGreaterThan(0);
  await expect
    .poll(() => [...traffic.pending].map((request) => request.url()), {
      timeout: resolveTimeout(120_000),
      message: "every live-data request the dashboard opened must complete",
    })
    .toEqual([]);

  expect(traffic.refused, "the proxy or the oauth2 gate refused live-data requests").toEqual([]);
  expect(traffic.streams, "event streams must open with 200 text/event-stream").toEqual([]);
  if (!isOnionUrl(shared.env.appBaseUrl)) {
    expect(traffic.failed, "requests or sockets to the canonical host failed in transport").toEqual([]);
    expect(traffic.consoleErrors, "the console reported transport errors for the canonical host").toEqual([]);
  }
}

exports.register = function (shared) {
  test("biber: the dashboard live updates reach it through the proxy with no transport error", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(300_000));
    expect(shared.env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
    expect(shared.env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();

    await expectLiveTraffic(page, shared, () =>
      shared.loginToDashboard(page, shared.env.biberUsername, shared.env.biberPassword),
    );

    await shared.logout(page);
  });

  test("guest: with SSO disabled the dashboard live updates reach it through the proxy", async ({ page }) => {
    skipUnlessServiceDisabled("sso");
    test.setTimeout(resolveTimeout(300_000));

    await expectLiveTraffic(page, shared, async () => {
      await shared.openApp(page, "/");
      await shared.expectDashboard(page, "with SSO disabled the dashboard is anonymous");
    });
  });
};
