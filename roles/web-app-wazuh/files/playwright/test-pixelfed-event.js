const { test, expect } = require("@playwright/test");
const { runAdminFlow, gotoOnion, decodeDotenvQuotedValue, normalizeBaseUrl } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");
const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

const pixelfedBaseUrl = normalizeBaseUrl(process.env.PIXELFED_BASE_URL || "");
const canaryMarker = decodeDotenvQuotedValue(process.env.CANARY_MARKER);
const httpCanaryRuleId = decodeDotenvQuotedValue(process.env.HTTP_CANARY_RULE_ID);
const alertsIndex = decodeDotenvQuotedValue(process.env.ALERTS_INDEX);
const canaryWaitMs = Number(process.env.CANARY_WAIT_MS);
const canaryPollMs = Number(process.env.CANARY_POLL_MS);
const pixelfedDecoder = decodeDotenvQuotedValue(process.env.PIXELFED_DECODER);
const pixelfedProgram = decodeDotenvQuotedValue(process.env.PIXELFED_PROGRAM);
const pixelfedLogLocal = process.env.PIXELFED_LOG_LOCAL === "true";
const pixelfedNode = decodeDotenvQuotedValue(process.env.PIXELFED_NODE);
const remoteAppSkip = decodeDotenvQuotedValue(process.env.REMOTE_APP_SKIP);

async function searchAlerts(page, marker) {
  const response = await page.request.post(
    `${shared.env.appBaseUrl}/api/console/proxy?path=${encodeURIComponent(`${alertsIndex}/_search`)}&method=POST`,
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

async function ensureAlertsIndexPattern(page) {
  const headers = { "osd-xsrf": "true", "content-type": "application/json" };
  const found = await page.request.get(
    `${shared.env.appBaseUrl}/api/saved_objects/_find?type=index-pattern&fields=title&per_page=1000`,
    { headers },
  );
  expect(found.status(), "saved objects find answered").toBe(200);
  const existing = (await found.json()).saved_objects.find((o) => o.attributes.title === alertsIndex);
  if (existing) return existing.id;
  const created = await page.request.post(
    `${shared.env.appBaseUrl}/api/saved_objects/index-pattern/${encodeURIComponent(alertsIndex)}`,
    { headers, data: { attributes: { title: alertsIndex, timeFieldName: "timestamp" } } },
  );
  expect(created.status(), "index pattern created").toBe(200);
  return (await created.json()).id;
}

test("administrator: a Pixelfed request shows up as its canary alert in the dashboard", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  skipUnlessServiceEnabled("pixelfed");
  test.skip(!pixelfedLogLocal, `pixelfed runs on ${pixelfedNode}; ${remoteAppSkip}, skipping the canary`);
  const marker = `pixelfed-pw-${Date.now()}`;

  await runAdminFlow(page, {
    adminInteraction: async (p) => {
      const probe = await p.context().newPage();
      await gotoOnion(probe, `${pixelfedBaseUrl}/${canaryMarker}%20${marker}`, { waitUntil: "domcontentloaded" });
      await probe.close();

      let hits = [];
      await expect
        .poll(async () => (hits = await searchAlerts(p, marker)).length, {
          timeout: resolveTimeout(canaryWaitMs),
          intervals: [canaryPollMs],
          message: `canary alert for ${marker} in ${alertsIndex}`,
        })
        .toBeGreaterThan(0);
      expect(hits[0]._source.decoder.name).toBe(pixelfedDecoder);
      expect(hits[0]._source.predecoder.program_name).toBe(pixelfedProgram);

      const indexPatternId = await ensureAlertsIndexPattern(p);
      const kuery = `rule.id:${httpCanaryRuleId} and full_log:"${marker}"`;
      await gotoOnion(
        p,
        `${shared.env.appBaseUrl}/app/data-explorer/discover#?_a=(metadata:(indexPattern:'${encodeURIComponent(indexPatternId)}',view:discover))&_q=(query:(language:kuery,query:'${encodeURIComponent(kuery)}'))&_g=(time:(from:now-1h,to:now))`,
        { waitUntil: "domcontentloaded" },
      );
      await expect(p.locator("body")).toContainText(marker, { timeout: resolveTimeout(60_000) });
    },
  });
});
