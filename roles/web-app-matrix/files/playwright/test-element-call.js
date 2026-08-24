const { test, expect } = require("./onion-test");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("element-call: Element config.json advertises a video-call backend when conferencing is enabled", async ({ request }) => {
    shared.skipUnlessServiceEnabled("element_call");
    const { elementBaseUrl } = shared.env;

    const configResponse = await request.get(`${elementBaseUrl}/config.json`, {
      failOnStatusCode: false,
      ignoreHTTPSErrors: true,
      timeout: resolveTimeout(30_000),
    });
    expect(configResponse.status(), `Element /config.json must serve when element_call is enabled`).toBe(200);

    const body = await configResponse.text();
    let config;
    try {
      config = JSON.parse(body);
    } catch (e) {
      throw new Error(`Element /config.json must be valid JSON: ${e.message}`, { cause: e });
    }

    const serializedConfig = JSON.stringify(config);
    const advertisesCallBackend =
      /element[_-]?call/i.test(serializedConfig) ||
      /jitsi/i.test(serializedConfig) ||
      /widget_build_url|widget_url|features\..*call/i.test(serializedConfig);

    expect(
      advertisesCallBackend,
      `Element /config.json must advertise a call backend (element_call / jitsi / widget_url / features.*call) when conferencing is enabled. Got keys: ${Object.keys(config).join(", ")}`,
    ).toBe(true);
  });
};
