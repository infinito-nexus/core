const { test, expect } = require("../onion-test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { decodeDotenvQuotedValue } = require("../personas");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

test("jitsi addon: Element advertises the co-deployed Jitsi deployment as its preferred domain", async ({ request }) => {
  skipUnlessAddonEnabled("jitsi");
  skipUnlessServiceEnabled("jitsi");

  test.setTimeout(resolveTimeout(60_000));

  const preferredDomain = decodeDotenvQuotedValue(process.env.JITSI_PREFERRED_DOMAIN);
  expect(preferredDomain, "JITSI_PREFERRED_DOMAIN must be set while the jitsi addon is enabled").toBeTruthy();

  const { elementBaseUrl } = shared.env;
  const response = await request.get(`${elementBaseUrl}/config.json`, {
    failOnStatusCode: false,
    timeout: resolveTimeout(30_000),
  });
  expect(response.status(), `Element /config.json must serve from ${elementBaseUrl}`).toBe(200);

  const body = await response.text();
  let config;
  try {
    config = JSON.parse(body);
  } catch (e) {
    throw new Error(`Element /config.json must be valid JSON: ${e.message}`, { cause: e });
  }

  expect(
    config.jitsi && config.jitsi.preferredDomain,
    `Element /config.json must carry jitsi.preferredDomain while the jitsi addon is enabled; without it every ` +
      `conference widget falls back to the public meet.jit.si instead of the co-deployed web-app-jitsi. ` +
      `Got keys: ${Object.keys(config).join(", ")}`,
  ).toBeTruthy();

  expect(
    config.jitsi.preferredDomain,
    `Element must point at the co-deployed Jitsi domain, not a third-party instance`,
  ).toBe(preferredDomain);
});
