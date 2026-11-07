const net = require("net");
const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { apiGetOnion } = require("./personas");

function tcpAccepts(host, port) {
  return new Promise((resolve) => {
    const socket = net.connect({ host, port });
    socket.setTimeout(resolveTimeout(5_000));
    socket.once("connect", () => {
      socket.destroy();
      resolve(true);
    });
    socket.once("timeout", () => {
      socket.destroy();
      resolve(false);
    });
    socket.once("error", () => resolve(false));
  });
}

exports.register = function (shared) {
  test("guest: no internal World Monitor service answers on the canonical host", async ({ request }) => {
    test.setTimeout(resolveTimeout(120_000)); // one bounded TCP probe per internal port plus the HTTP probe
    expect(shared.env.internalTcpPorts.length, "INTERNAL_TCP_PORTS_JSON must list the internal ports").toBeGreaterThan(0);
    for (const port of shared.env.internalTcpPorts) {
      expect(
        await tcpAccepts(shared.env.canonicalDomain, port),
        `internal port ${port} must not accept connections on ${shared.env.canonicalDomain}`,
      ).toBe(false);
    }
    const response = await apiGetOnion(request, `http://${shared.env.canonicalDomain}/`, {
      failOnStatusCode: false,
      maxRedirects: 0,
      timeout: resolveTimeout(30_000),
    });
    expect(await response.text(), "port 80 must be the platform proxy, not the redis-rest bridge").not.toContain(
      "Serverless Redis HTTP",
    );
  });
};
