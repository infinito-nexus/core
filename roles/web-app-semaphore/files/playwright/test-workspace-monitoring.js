const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, performKeycloakLoginForm } = require("./personas");
const workspaces = require("./workspace-fixture");

const LABEL = "administrator-monitoring";
const MONITORING_TEMPLATE = "monitoring";
const SSH_PORT = 22;
const HTTPS_PORT = 443;
const AGENT_AND_TRAFFIC_OFF = { platform_monitoring: { agent: false, traffic: false } };
const TRAFFIC_SERIES = "nginx_";
const HEALTH_SERIES = "stack_up";

const SETUP_MS = 125 * 60_000;
const CLEANUP_MS = 65 * 60_000;
const DEPLOY_MS = 70 * 60_000;
const RUN_MS = 15 * 60_000;
const SCRAPE_MS = 5 * 60_000;
const REQUEST_MS = 30_000;
const POLL_MS = 15_000;

const checkmkBaseUrl = normalizeBaseUrl(process.env.CHECKMK_BASE_URL || "");
const checkmkSite = decodeDotenvQuotedValue(process.env.CHECKMK_SITE || "");
const prometheusBaseUrl = normalizeBaseUrl(process.env.PROMETHEUS_BASE_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD);

/**
 * Args:
 *   run: a finished `monitoring` task.
 *   workspace: the bare workspace id it ran for.
 *
 * Returns:
 *   `checkmk` and `prometheus` of its last output line, which names exactly
 *   the workspace and MONITOR_HOST.
 */
function monitoringResult(run, workspace, host) {
  workspaces.expectSucceeded(run, `${LABEL}: the monitoring run`);
  const result = JSON.parse(workspaces.lastLine(run.lines));
  expect(Object.keys(result).sort(), `${LABEL}: the last line holds exactly workspace, host, checkmk and prometheus`).toEqual([
    "checkmk",
    "host",
    "prometheus",
    "workspace",
  ]);
  expect(result.workspace, `${LABEL}: the last line names its workspace`).toBe(workspace);
  expect(result.host, `${LABEL}: the last line names MONITOR_HOST`).toBe(host);
  return { checkmk: result.checkmk, prometheus: result.prometheus };
}

/**
 * Args:
 *   target: `sharedTarget` of the workspace fixture.
 *
 * Returns:
 *   The host variables the template reads without a fallback: the address,
 *   the pinned host key and the Prometheus domain of the instance.
 */
function monitoredVars(target) {
  const vars = process.env.SEMAPHORE_DEPLOY_TARGET_VARS_JSON;
  expect(vars, `${LABEL}: SEMAPHORE_DEPLOY_TARGET_VARS_JSON must be set`).toBeTruthy();
  const primary = JSON.parse(decodeDotenvQuotedValue(vars)).DOMAIN_PRIMARY;
  expect(typeof primary === "string" && primary.length > 0, `${LABEL}: the shared target must name its DOMAIN_PRIMARY`).toBe(true);
  return {
    ansible_host: target.address,
    ssh_host_key: target.hostKey,
    applications: { "web-app-prometheus": { server: { domains: { canonical: [`prometheus.${primary}`] } } } },
  };
}

/**
 * Args:
 *   page: a page of the browser context the sign-in lands in.
 *   url: an SSO-gated page.
 *   username, password: the account that signs in.
 */
async function signIn(page, url, username, password) {
  await gotoOnion(page, url, { timeout: resolveTimeout(REQUEST_MS) });
  if (/\/realms\//.test(page.url())) {
    await performKeycloakLoginForm(page, username, password);
  }
}

/**
 * Args:
 *   page: a page signed in to the platform's Prometheus.
 *   query: a PromQL instant query.
 *
 * Returns:
 *   The result vector.
 */
async function promql(page, query) {
  const response = await page.request.get(`${prometheusBaseUrl}/api/v1/query?query=${encodeURIComponent(query)}`, {
    timeout: resolveTimeout(REQUEST_MS),
  });
  expect(response.status(), `${LABEL}: Prometheus must answer ${query}`).toBe(200);
  return (await response.json()).data.result;
}

exports.register = function (shared) {
  test.describe("workspace monitoring template", () => {
    test.describe.configure({ retries: 0, mode: "serial" });
    let own;
    let workspace;
    let platform;
    let template;
    let instance;
    let monitored;

    async function monitor(action, label) {
      const run = await workspaces.runTemplate(
        shared,
        own.page,
        platform.id,
        template.id,
        { WORKSPACE: own.workspace, MONITOR_ACTION: action, MONITOR_HOST: instance.target.address, INVENTORY_COMMIT: instance.commit },
        RUN_MS,
        `${LABEL}: ${label}`,
      );
      return monitoringResult(run, own.workspace, instance.target.address);
    }

    async function checkmkHosts(page) {
      const response = await page.request.get(
        `${checkmkBaseUrl}/${checkmkSite}/check_mk/api/1.0/objects/folder_config/~workspaces~${workspace}/collections/hosts`,
        { headers: { Accept: "application/json" }, timeout: resolveTimeout(REQUEST_MS) },
      );
      if (response.status() === 404) {
        return [];
      }
      expect(response.status(), `${LABEL}: Checkmk must list the workspace folder`).toBe(200);
      return (await response.json()).value;
    }

    async function seriesOf(page, kind) {
      return promql(page, `count by (instance) ({workspace="${workspace}", instance="${instance.target.address}", __name__=~"${kind}.*"})`);
    }

    test.beforeAll(async ({ browser }) => {
      workspaces.skipUnlessWorkspaces();
      test.skip(!checkmkBaseUrl || !checkmkSite || !prometheusBaseUrl, "the Semaphore variant deploys no web-app-checkmk or web-app-prometheus");
      test.setTimeout(resolveTimeout(SETUP_MS));
      own = workspaces.workspaceFixture();
      const address = await workspaces.sharedTargetAddress();
      await workspaces.openWorkspace(shared, browser, own, `${address}:${SSH_PORT},${address}:${HTTPS_PORT}`, LABEL);
      workspace = `ws-${own.workspace}`;
      platform = await workspaces.namedProject(shared, own.page, decodeDotenvQuotedValue(process.env.SEMAPHORE_WORKSPACES_PROJECT_NAME));
      template = await workspaces.namedTemplate(shared, own.page, platform.id, MONITORING_TEMPLATE);
      monitored = monitoredVars(await workspaces.sharedTarget(shared, own.page));
      instance = await workspaces.deployToSharedTarget(shared, own, { roles: ["web-app-prometheus"], hostVars: monitored }, LABEL);
    });

    test.afterAll(async () => {
      test.setTimeout(resolveTimeout(CLEANUP_MS));
      if (own && own.context) {
        if (template && instance) {
          await monitor("remove", "cleanup remove");
        }
        await workspaces.closeWorkspace(shared, own, LABEL);
      }
    });

    test("monitoring: the template takes WORKSPACE, MONITOR_ACTION, MONITOR_HOST and INVENTORY_COMMIT only and refuses anything else", async () => {
      test.setTimeout(resolveTimeout(4 * RUN_MS));
      expect(workspaces.surveyOf(template).map((variable) => variable.name).sort()).toEqual([
        "INVENTORY_COMMIT",
        "MONITOR_ACTION",
        "MONITOR_HOST",
        "WORKSPACE",
      ]);
      workspaces.expectLockedTemplate(template, LABEL);
      const host = instance.target.address;
      for (const survey of [
        { WORKSPACE: workspace, MONITOR_ACTION: "apply", MONITOR_HOST: host, INVENTORY_COMMIT: instance.commit },
        { WORKSPACE: own.workspace, MONITOR_ACTION: "destroy", MONITOR_HOST: host, INVENTORY_COMMIT: instance.commit },
        { WORKSPACE: own.workspace, MONITOR_ACTION: "apply", MONITOR_HOST: "bad host", INVENTORY_COMMIT: instance.commit },
      ]) {
        const run = await workspaces.runTemplate(shared, own.page, platform.id, template.id, survey, RUN_MS, `${LABEL}: refusal`);
        const last = JSON.parse(workspaces.lastLine(run.lines));
        expect(run.task.status, `${LABEL}: a refused survey ends in error`).toBe("error");
        expect(Object.keys(last), `${LABEL}: the refusal line keeps the decision 28 format`).toEqual(["workspace", "refused"]);
      }
    });

    test("monitoring: apply with every kind on puts the target in Checkmk and Prometheus", async () => {
      test.setTimeout(resolveTimeout(2 * RUN_MS + SCRAPE_MS));
      const outcome = await monitor("apply", "apply all on");
      expect(outcome).toEqual({ checkmk: true, prometheus: true });
      expect(await monitor("apply", "second apply"), `${LABEL}: a second apply reports the same outcome`).toEqual(outcome);
    });

    test("monitoring: the administrator finds the target in /workspaces with green checks", async ({ browser }) => {
      test.setTimeout(resolveTimeout(SCRAPE_MS + 4 * REQUEST_MS));
      const context = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        const page = await context.newPage();
        await signIn(page, `${checkmkBaseUrl}/${checkmkSite}/check_mk/`, adminUsername, adminPassword);
        const [host] = (await checkmkHosts(page)).filter(
          (entry) => entry.extensions.attributes.labels.instance === instance.target.address,
        );
        expect(host, `${LABEL}: /workspaces/${workspace} must hold the target`).toBeTruthy();
        expect(host.extensions.attributes.labels.workspace).toBe(workspace);
        await expect
          .poll(
            async () => {
              const response = await page.request.get(
                `${checkmkBaseUrl}/${checkmkSite}/check_mk/api/1.0/objects/host/${encodeURIComponent(host.id)}/collections/services?columns=state&columns=description`,
                { headers: { Accept: "application/json" }, timeout: resolveTimeout(REQUEST_MS) },
              );
              const services = (await response.json()).value || [];
              return services.length > 0 && services.every((service) => service.extensions.state === 0);
            },
            { timeout: resolveTimeout(SCRAPE_MS), intervals: [POLL_MS] },
          )
          .toBe(true);
      } finally {
        await context.close();
      }
    });

    test("monitoring: agent and traffic off drop the agent and the traffic series only", async ({ browser }) => {
      test.setTimeout(resolveTimeout(DEPLOY_MS + RUN_MS + 2 * SCRAPE_MS));
      instance = await workspaces.deployToSharedTarget(shared, own, { roles: ["web-app-prometheus"], hostVars: { ...monitored, ...AGENT_AND_TRAFFIC_OFF } }, LABEL);
      expect(await monitor("apply", "apply agent and traffic off")).toEqual({ checkmk: true, prometheus: true });
      const context = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        const page = await context.newPage();
        await signIn(page, `${prometheusBaseUrl}/`, adminUsername, adminPassword);
        await expect.poll(async () => (await seriesOf(page, TRAFFIC_SERIES)).length, { timeout: resolveTimeout(SCRAPE_MS), intervals: [POLL_MS] }).toBe(0);
        expect((await seriesOf(page, HEALTH_SERIES)).length, `${LABEL}: ${HEALTH_SERIES} must still arrive`).toBeGreaterThan(0);
        await signIn(page, `${checkmkBaseUrl}/${checkmkSite}/check_mk/`, adminUsername, adminPassword);
        const [host] = (await checkmkHosts(page)).filter(
          (entry) => entry.extensions.attributes.labels.instance === instance.target.address,
        );
        expect(host.extensions.attributes.tag_agent, `${LABEL}: agent off leaves no agent data source`).toBe("no-agent");
      } finally {
        await context.close();
      }
    });

    test("monitoring: an account without the administrator role sees no customer host or series", async ({ browser }) => {
      test.setTimeout(resolveTimeout(6 * REQUEST_MS));
      const context = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        const page = await context.newPage();
        await signIn(page, `${checkmkBaseUrl}/${checkmkSite}/check_mk/`, biberUsername, biberPassword);
        const response = await page.request.get(
          `${checkmkBaseUrl}/${checkmkSite}/check_mk/api/1.0/domain-types/host/collections/all?query=${encodeURIComponent(
            JSON.stringify({ op: "~", left: "name", right: "^ws-" }),
          )}`,
          { headers: { Accept: "application/json" }, timeout: resolveTimeout(REQUEST_MS) },
        );
        const visible = response.status() === 200 ? (await response.json()).value || [] : [];
        expect(visible, `${LABEL}: a non-administrator must see no /workspaces host`).toEqual([]);
        await signIn(page, `${prometheusBaseUrl}/`, biberUsername, biberPassword);
        const series = await page.request.get(`${prometheusBaseUrl}/api/v1/query?query=${encodeURIComponent(`{workspace="${workspace}"}`)}`, {
          timeout: resolveTimeout(REQUEST_MS),
        });
        const answered = series.status() === 200 && (await series.text()).includes('"result":[{');
        expect(answered, `${LABEL}: a non-administrator must read no customer series`).toBe(false);
      } finally {
        await context.close();
      }
    });

    test("monitoring: remove clears Checkmk and Prometheus and a second remove changes nothing", async ({ browser }) => {
      test.setTimeout(resolveTimeout(2 * RUN_MS + SCRAPE_MS));
      expect(await monitor("remove", "remove")).toEqual({ checkmk: false, prometheus: false });
      expect(await monitor("remove", "second remove"), `${LABEL}: removing an unknown host changes nothing`).toEqual({
        checkmk: false,
        prometheus: false,
      });
      const context = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        const page = await context.newPage();
        await signIn(page, `${checkmkBaseUrl}/${checkmkSite}/check_mk/`, adminUsername, adminPassword);
        expect(await checkmkHosts(page), `${LABEL}: remove must drop the workspace folder`).toEqual([]);
      } finally {
        await context.close();
      }
    });
  });
};
