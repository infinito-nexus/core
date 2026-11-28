const { test, expect } = require("@playwright/test");
const { gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");
const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

test("administrator: searches the logs of a deployed application and finds the line the test wrote", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  skipUnlessServiceEnabled("loki");
  test.setTimeout(resolveTimeout(300_000));
  const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const page = await ctx.newPage();
    await shared.loginViaOidc(page, shared.env.adminUsername, shared.env.adminPassword);
    const runId = await shared.writeProbeLine(page, []);
    const query = `{application="${shared.env.probeApplication}"} |= "/${shared.LOG_PROBE_SEGMENT}/"`;
    await expect
      .poll(
        async () => {
          await gotoOnion(page, shared.exploreUrl(query), { waitUntil: "domcontentloaded" });
          await page.waitForLoadState("networkidle", { timeout: resolveTimeout(15_000) }).catch(() => {});
          return page.locator("body").innerText();
        },
        {
          timeout: resolveTimeout(180_000),
          intervals: [5_000, 10_000, 15_000],
          message: `Explore MUST list the ${shared.env.probeApplication} line carrying ${runId} within the poll window`,
        },
      )
      .toContain(runId);
  } finally {
    await ctx.close().catch(() => {});
  }
});

test("rbac: a member of auditor reads logs and cannot change datasources, dashboards or alert rules", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  skipUnlessServiceEnabled("loki");
  test.setTimeout(resolveTimeout(240_000));
  await shared.withBiberInGroup(browser, shared.env.auditorGroupPath, async () => {
    const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
    try {
      const page = await ctx.newPage();
      await shared.loginViaOidc(page, shared.env.biberUsername, shared.env.biberPassword);

      const read = await shared.grafanaApi(page, "POST", "/api/ds/query", {
        from: "now-15m",
        to: "now",
        queries: [
          {
            refId: "A",
            datasource: { type: "loki", uid: shared.env.lokiUid },
            expr: '{log_class=~".+"}',
            queryType: "range",
            maxLines: 10,
          },
        ],
      });
      expect(read.status(), `the auditor MUST query Loki, got ${await read.text()}`).toBe(200);

      const writes = [
        ["POST", "/api/datasources", { name: `auditor-probe-${Date.now()}`, type: "loki", access: "proxy", url: "http://127.0.0.1:1" }],
        [
          "POST",
          "/api/dashboards/db",
          { dashboard: { title: `auditor-probe-${Date.now()}`, panels: [], schemaVersion: 39 }, overwrite: false },
        ],
        [
          "POST",
          "/api/v1/provisioning/alert-rules",
          { title: `auditor-probe-${Date.now()}`, ruleGroup: "auditor-probe", folderUID: "general", condition: "A", data: [], for: "1m" },
        ],
      ];
      for (const [method, path, body] of writes) {
        const response = await shared.grafanaApi(page, method, path, body);
        expect(
          response.status(),
          `the auditor MUST NOT ${method} ${path}; Grafana answered ${response.status()} ${await response.text()}`,
        ).toBe(403);
      }
    } finally {
      await ctx.close().catch(() => {});
    }
  });
});

test("administrator: the Prometheus datasource is provisioned beside Loki", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  skipUnlessServiceEnabled("prometheus");
  test.setTimeout(resolveTimeout(180_000));
  const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const page = await ctx.newPage();
    await shared.loginViaOidc(page, shared.env.adminUsername, shared.env.adminPassword);
    const health = await shared.grafanaApi(page, "GET", `/api/datasources/uid/${shared.env.prometheusUid}/health`);
    expect(health.status(), `the Prometheus datasource MUST answer its health check: ${await health.text()}`).toBe(200);
  } finally {
    await ctx.close().catch(() => {});
  }
});
