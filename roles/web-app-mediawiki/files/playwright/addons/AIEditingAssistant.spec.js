const { test, expect } = require("@playwright/test");

const { skipUnlessAddonEnabled } = require("../addon-gating");
const { normalizeBaseUrl } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const aiGatewayBaseUrl = normalizeBaseUrl(process.env.AI_GATEWAY_BASE_URL || "");

const PROMPT_ROUTE = "/rest.php/aieditingassistant/v1/prompt";

test("AIEditingAssistant: the wiki answers a prompt through the in-cluster gateway", async ({
  request,
}) => {
  skipUnlessAddonEnabled("AIEditingAssistant");
  test.setTimeout(240_000);

  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(aiGatewayBaseUrl, "AI_GATEWAY_BASE_URL must be set").toBeTruthy();

  const gateway = new URL(aiGatewayBaseUrl);
  const wikiHost = new URL(appBaseUrl).host;

  expect(
    gateway.protocol,
    `the AI base URL must stay on the container network (plain http), got ${aiGatewayBaseUrl}`,
  ).toBe("http:");
  expect(
    gateway.hostname.includes("."),
    "the AI base URL host must be an undotted compose/swarm service name; a dotted host is " +
      `resolved through the dns-search suffix and leaves via the public ingress (got ${aiGatewayBaseUrl})`,
  ).toBe(false);
  expect(
    gateway.host,
    "the AI base URL must point at the gateway, not back at the wiki itself",
  ).not.toBe(wikiHost);

  const siteinfo = await request.get(
    `${appBaseUrl}/api.php?action=query&meta=siteinfo&siprop=extensions&format=json&formatversion=2`,
    { timeout: 60_000 },
  );
  expect(
    siteinfo.status(),
    "the MediaWiki action API must answer so the loaded extension list can be read",
  ).toBe(200);
  const installed = ((await siteinfo.json()).query?.extensions || []).map(
    (extension) => extension.name,
  );
  expect(
    installed,
    "AIEditingAssistant is not in the loaded extension list, so LocalSettings.php never " +
      "reached its wfLoadExtension block (extension missing, or VisualEditor/VisualEditorPlus " +
      "not loaded ahead of it)",
  ).toContain("AIEditingAssistant");

  const response = await request.post(`${appBaseUrl}${PROMPT_ROUTE}`, {
    data: {
      command: "Fix grammar and punctuation in this text",
      text: "this sentence have a error",
      isContinuation: false,
    },
    timeout: 210_000,
  });

  const bodyText = await response.text();
  expect(
    response.status(),
    `POST ${PROMPT_ROUTE} returned ${response.status()}: ${bodyText.slice(0, 500)}. ` +
      "400 means $wgAIEditingAssistantActiveProvider is unset or unknown; 500 means the " +
      "provider reached no working gateway leg (wrong base URL, rejected virtual key, or a " +
      `model the gateway does not serve). Configured gateway: ${aiGatewayBaseUrl}.`,
  ).toBe(200);

  const body = JSON.parse(bodyText);
  expect(
    body.success,
    "the prompt handler must report success, proving the provider completed the round-trip",
  ).toBe(true);
  expect(
    String(body.result || "").trim().length,
    "the gateway must return a real, non-empty completion; an empty result means the model " +
      "answered nothing and the surface is wired but useless",
  ).toBeGreaterThan(0);
});
