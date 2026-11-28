const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");
const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

const ALERT_WORD = "critical";

/**
 * The firing instance of the provisioned log alert for the probe
 * application, or null while there is none.
 *
 * Args:
 *   page: a Playwright page whose context carries an admin session.
 */
async function firingLogAlert(page) {
  const response = await shared.grafanaApi(page, "GET", "/api/prometheus/grafana/api/v1/alerts");
  if (response.status() !== 200) {
    return null;
  }
  const alerts = (await response.json()).data?.alerts || [];
  return (
    alerts.find(
      (alert) =>
        alert.labels?.alertname === shared.env.alertTitle &&
        alert.labels?.application === shared.env.probeApplication &&
        /^alerting/i.test(alert.state || ""),
    ) || null
  );
}

/**
 * Write a critical probe line into the proxy's error log, the application
 * log class the alert reads, and wait until the log alert fires for it.
 *
 * Args:
 *   page: a Playwright page whose context carries an admin session.
 *
 * Returns:
 *   The firing alert instance.
 */
async function fireLogAlert(page) {
  await shared.writeProbeErrorLine(page, [ALERT_WORD]);
  let instance = null;
  await expect
    .poll(
      async () => {
        instance = await firingLogAlert(page);
        return instance !== null;
      },
      {
        timeout: resolveTimeout(240_000),
        intervals: [5_000, 10_000, 15_000],
        message: `"${shared.env.alertTitle}" MUST fire for ${shared.env.probeApplication} after a "${ALERT_WORD}" line`,
      },
    )
    .toBe(true);
  return instance;
}

/**
 * Receivers Grafana's Alertmanager routes the firing log alert to.
 *
 * Args:
 *   page: a Playwright page whose context carries an admin session.
 */
async function routedReceivers(page) {
  const response = await shared.grafanaApi(page, "GET", "/api/alertmanager/grafana/api/v2/alerts");
  if (response.status() !== 200) {
    return [];
  }
  const alert = (await response.json()).find(
    (candidate) =>
      candidate.labels?.alertname === shared.env.alertTitle &&
      candidate.labels?.application === shared.env.probeApplication &&
      candidate.status?.state === "active",
  );
  return (alert?.receivers || []).map((receiver) => receiver.name);
}

/**
 * Delivery state of the Alertmanager contact point since `since`:
 * "delivered" after an attempt without error, "error: <text>" after a
 * failed attempt, "pending" before any attempt.
 *
 * Args:
 *   page: a Playwright page whose context carries an admin session.
 *   since: epoch milliseconds the attempt must not predate.
 */
async function deliveryState(page, since) {
  const response = await shared.grafanaApi(page, "GET", "/api/alertmanager/grafana/config/api/v1/receivers");
  if (response.status() !== 200) {
    return `pending: receivers status answered ${response.status()}`;
  }
  const receiver = (await response.json()).find((candidate) => candidate.name === shared.env.alertReceiver);
  const attempts = (receiver?.integrations || []).filter(
    (integration) => Date.parse(integration.lastNotifyAttempt || "") >= since,
  );
  if (attempts.length === 0) {
    return "pending";
  }
  const failed = attempts.find((integration) => integration.lastNotifyAttemptError);
  return failed ? `error: ${failed.lastNotifyAttemptError}` : "delivered";
}

test("administrator: a synthetic critical line fires the Grafana log alert", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  skipUnlessServiceEnabled("loki");
  test.setTimeout(resolveTimeout(360_000)); // OIDC login, collector shipping, then the rule's 1m evaluation over a 5m window
  const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const page = await ctx.newPage();
    await shared.loginViaOidc(page, shared.env.adminUsername, shared.env.adminPassword);
    const instance = await fireLogAlert(page);
    expect(instance.labels.application, "the alert MUST name the application that wrote the line").toBe(
      shared.env.probeApplication,
    );
  } finally {
    await ctx.close().catch(() => {});
  }
});

test("administrator: the fired log alert notifies the Alertmanager of web-app-prometheus", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  skipUnlessServiceEnabled("loki");
  skipUnlessServiceEnabled("prometheus");
  test.setTimeout(resolveTimeout(840_000)); // firing as above, then Grafana's 5m group_interval when the alert group already notified
  const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const page = await ctx.newPage();
    await shared.loginViaOidc(page, shared.env.adminUsername, shared.env.adminPassword);
    const instance = await fireLogAlert(page);
    const activeAt = Date.parse(instance.activeAt);
    expect(Number.isNaN(activeAt), `the firing alert MUST carry its activeAt, got ${instance.activeAt}`).toBe(false);
    await expect
      .poll(() => routedReceivers(page), {
        timeout: resolveTimeout(120_000),
        intervals: [5_000, 10_000],
        message: `Grafana MUST route the firing alert to the "${shared.env.alertReceiver}" contact point`,
      })
      .toContain(shared.env.alertReceiver);
    await expect
      .poll(() => deliveryState(page, activeAt), {
        timeout: resolveTimeout(420_000),
        intervals: [10_000, 15_000, 30_000],
        message: `the "${shared.env.alertReceiver}" contact point MUST deliver the alert to the Alertmanager without error`,
      })
      .toBe("delivered");
  } finally {
    await ctx.close().catch(() => {});
  }
});
