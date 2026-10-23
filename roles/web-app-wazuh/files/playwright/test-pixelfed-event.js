const { test, expect } = require("@playwright/test");
const { runAdminFlow, gotoOnion, decodeDotenvQuotedValue, normalizeBaseUrl } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");
const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

const pixelfedBaseUrl = normalizeBaseUrl(process.env.PIXELFED_BASE_URL || "");
const canaryMarker = decodeDotenvQuotedValue(process.env.CANARY_MARKER);
const httpCanaryRuleId = decodeDotenvQuotedValue(process.env.HTTP_CANARY_RULE_ID);

async function searchAlerts(page, marker) {
  const response = await page.request.post(
    `${shared.env.appBaseUrl}/api/console/proxy?path=${encodeURIComponent("wazuh-alerts-*/_search")}&method=POST`,
    {
      headers: { "osd-xsrf": "true", "content-type": "application/json" },
      data: {
        size: 1,
        query: {
          bool: {
            filter: [
              { term: { "rule.id": httpCanaryRuleId } },
              { match_phrase: { full_log: marker } },
            ],
          },
        },
      },
    },
  );
  expect(response.status(), "dashboard console proxy answered").toBe(200);
  return (await response.json()).hits.hits;
}

test("administrator: a Pixelfed request shows up as its canary alert in the dashboard", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  skipUnlessServiceEnabled("pixelfed");
  const marker = `pixelfed-pw-${Date.now()}`;

  await runAdminFlow(page, {
    adminInteraction: async (p) => {
      const probe = await p.context().newPage();
      await gotoOnion(probe, `${pixelfedBaseUrl}/${canaryMarker}%20${marker}`, { waitUntil: "domcontentloaded" });
      await probe.close();

      let hits = [];
      await expect
        .poll(async () => (hits = await searchAlerts(p, marker)).length, {
          timeout: resolveTimeout(180_000),
          intervals: [5_000],
          message: `canary alert for ${marker} in wazuh-alerts-*`,
        })
        .toBeGreaterThan(0);
      expect(hits[0]._source.decoder.name).toBe("infinito-pixelfed");
      expect(hits[0]._source.predecoder.program_name).toBe("pixelfed");

      const kuery = `rule.id:${httpCanaryRuleId} and full_log:"${marker}"`;
      await gotoOnion(
        p,
        `${shared.env.appBaseUrl}/app/data-explorer/discover#?_q=(query:(language:kuery,query:'${encodeURIComponent(kuery)}'))&_g=(time:(from:now-1h,to:now))`,
        { waitUntil: "domcontentloaded" },
      );
      await expect(p.locator("body")).toContainText(marker, { timeout: resolveTimeout(60_000) });
    },
  });
});
