const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

test("notify_push addon: the push server authenticates a client over the announced websocket", async ({ browser }) => {
  skipUnlessAddonEnabled("notify_push");
  test.setTimeout(resolveTimeout(120_000));

  const expectedWebsocket = new URL("push/ws", shared.env.nextcloudBaseUrl);
  expectedWebsocket.protocol = expectedWebsocket.protocol === "https:" ? "wss:" : "ws:";

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    const capabilitiesUrl = new URL(
      "ocs/v2.php/cloud/capabilities?format=json",
      shared.env.nextcloudBaseUrl,
    ).toString();
    const capabilitiesResponse = await page.request.get(capabilitiesUrl, {
      headers: { "OCS-APIRequest": "true", Accept: "application/json" },
    });
    expect(capabilitiesResponse.ok(), "the OCS capabilities endpoint must respond").toBeTruthy();
    const capabilitiesBody = await capabilitiesResponse.json();
    const endpoints = capabilitiesBody?.ocs?.data?.capabilities?.notify_push?.endpoints;
    expect(
      endpoints?.websocket,
      "Nextcloud announces the push websocket only after occ notify_push:setup passed its self-test and stored base_endpoint",
    ).toBe(expectedWebsocket.toString());
    expect(
      endpoints?.pre_auth,
      "a signed-in user must be offered the notify_push pre_auth endpoint",
    ).toBeTruthy();

    const authenticate = async () => {
      const preAuthResponse = await page.request.post(endpoints.pre_auth, {
        headers: { "OCS-APIRequest": "true" },
      });
      if (!preAuthResponse.ok()) {
        return `pre_auth answered HTTP ${preAuthResponse.status()}`;
      }
      const token = (await preAuthResponse.text()).trim();
      return page.evaluate(
        ({ url, preAuthToken, timeoutMs }) =>
          new Promise((resolve) => {
            const socket = new WebSocket(url);
            const timer = setTimeout(() => {
              socket.close();
              resolve("no answer from the push server");
            }, timeoutMs);
            socket.addEventListener("open", () => {
              socket.send("");
              socket.send(preAuthToken);
            });
            socket.addEventListener("message", (event) => {
              clearTimeout(timer);
              socket.close();
              resolve(String(event.data));
            });
            socket.addEventListener("error", () => {
              clearTimeout(timer);
              resolve("websocket error");
            });
          }),
        { url: endpoints.websocket, preAuthToken: token, timeoutMs: 10_000 },
      );
    };

    await expect
      .poll(authenticate, {
        timeout: resolveTimeout(60_000),
        message: `the push server behind ${endpoints.websocket} must accept a pre_auth token and answer "authenticated", proving the /push/ proxy chain, the daemon and its redis subscription`,
      })
      .toBe("authenticated");
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
