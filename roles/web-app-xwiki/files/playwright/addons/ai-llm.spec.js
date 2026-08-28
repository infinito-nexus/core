const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");

const { skipUnlessAddonEnabled } = require("../addon-gating");
const {
  decodeDotenvQuotedValue,
  normalizeBaseUrl,
  gotoOnion,
} = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const aiGatewayBaseUrl = normalizeBaseUrl(process.env.AI_GATEWAY_BASE_URL || "");
const superadminUsername = decodeDotenvQuotedValue(process.env.XWIKI_SUPERADMIN_USERNAME || "");
const superadminPassword = decodeDotenvQuotedValue(process.env.XWIKI_SUPERADMIN_PASSWORD || "");

const EXTENSION_ID = "org.xwiki.contrib.llm:application-ai-llm-ui";

test("ai-llm: the AI LLM Application extension is installed on the wiki", async ({ page }) => {
  skipUnlessAddonEnabled("ai-llm");
  test.setTimeout(resolveTimeout(120_000));

  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();

  const gatewayHost = new URL(aiGatewayBaseUrl).hostname;
  expect(
    gatewayHost.includes("."),
    `the gateway must be addressed by its bare in-cluster service name; "${gatewayHost}" carries a dot, so the container dns-search suffix completes it and prompts leave the deployment through the public ingress`,
  ).toBe(false);

  expect(superadminUsername, "XWIKI_SUPERADMIN_USERNAME must be set").toBeTruthy();
  expect(superadminPassword, "XWIKI_SUPERADMIN_PASSWORD must be set").toBeTruthy();

  const installed = await page.request.get(
    `${appBaseUrl}/rest/extensions/${encodeURIComponent(EXTENSION_ID)}`,
    {
      headers: { Accept: "application/json" },
      params: { media: "json" },
      failOnStatusCode: false,
      timeout: resolveTimeout(60_000),
    },
  );

  expect(
    installed.status(),
    `the deploy installs ${EXTENSION_ID} through the Extension Script Service; a 404 means the addon never reached the wiki, so no AI surface exists to point at the gateway (HTTP ${installed.status()})`,
  ).toBe(200);

  await gotoOnion(page, `${appBaseUrl}/`, { waitUntil: "domcontentloaded" }).catch(() => {});
});
