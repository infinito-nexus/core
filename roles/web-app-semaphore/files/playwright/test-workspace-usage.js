const dns = require("node:dns");
const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { keycloakAdminToken, requireDotenvValue } = require("./personas");
const workspaces = require("./workspace-fixture");

const LABEL = "administrator-usage";
const USAGE_TEMPLATE = "usage";
const SSH_PORT = 22;
const HTTPS_PORT = 443;
const PAGE = 100;
const DAILY = /^[0-5]?[0-9] (1?[0-9]|2[0-3]) \* \* \*$/;
const PROBE_USER = { username: "usageprobe", firstName: "Usage", lastName: "Probe", email: "usageprobe@example.org" };
const USAGE_HOST_VARS = { applications: { "web-app-keycloak": { services: { keycloak: { usage_client: { enabled: true } } } } } };

const SETUP_MS = 125 * 60_000;
const CLEANUP_MS = 65 * 60_000;
const USAGE_RUN_MS = 10 * 60_000;
const REQUEST_MS = 30_000;

const targetHost = requireDotenvValue(process.env.SEMAPHORE_DEPLOY_TARGET_HOST, "SEMAPHORE_DEPLOY_TARGET_HOST");

async function targetAddress() {
  return (await dns.promises.lookup(targetHost, { family: 4 })).address;
}

function bearer(token) {
  return { Authorization: `Bearer ${token}` };
}

/**
 * Args:
 *   run: a finished `usage` task.
 *
 * Returns:
 *   The result object of its last output line.
 */
function usageResult(run) {
  workspaces.expectSucceeded(run, `${LABEL}: the usage run`);
  const result = JSON.parse(workspaces.lastLine(run.lines));
  expect(Object.keys(result).sort(), `${LABEL}: the usage line must hold exactly its three fields`).toEqual([
    "counted_at",
    "hosts",
    "workspace",
  ]);
  return result;
}

exports.register = function (shared) {
  test.describe("workspace usage template", () => {
    test.describe.configure({ retries: 0, mode: "serial" });
    let own;
    let address;
    let instance;

    async function usageTemplate() {
      const project = await workspaces.namedProject(shared, own.page, own.result.alias);
      return { project, template: await workspaces.namedTemplate(shared, own.page, project.id, USAGE_TEMPLATE) };
    }

    /**
     * Returns:
     *   The `active_users` the usage task reports for the shared target.
     */
    async function countedPeople() {
      const { project, template } = await usageTemplate();
      const run = await workspaces.runTemplate(shared, own.page, project.id, template.id, {}, USAGE_RUN_MS, `${LABEL}: usage`);
      const result = usageResult(run);
      expect(result.workspace, `${LABEL}: the usage line must name its workspace`).toBe(own.workspace);
      const [entry] = result.hosts.filter((host) => host.host === address);
      expect(entry, `${LABEL}: the usage line must report the shared target ${address}`).toBeTruthy();
      expect(Object.keys(entry).sort(), `${LABEL}: a host entry holds exactly host, realm and active_users`).toEqual([
        "active_users",
        "host",
        "realm",
      ]);
      return entry.active_users;
    }

    async function adminToken() {
      return keycloakAdminToken(instance.request, instance.baseUrl, instance.adminUsername, instance.adminPassword);
    }

    /**
     * Returns:
     *   The enabled people of the instance's realm, read with its master administrator.
     */
    async function enabledPeople() {
      const token = await adminToken();
      let people = 0;
      for (let first = 0; ; first += PAGE) {
        const response = await instance.request.get(
          `${instance.baseUrl}/admin/realms/${encodeURIComponent(instance.realm)}/users?first=${first}&max=${PAGE}&briefRepresentation=false`,
          { headers: bearer(token), timeout: resolveTimeout(REQUEST_MS) },
        );
        expect(response.status(), `${LABEL}: the administrator must list the users of the instance`).toBe(200);
        const page = await response.json();
        people += page.filter(
          (user) => user.enabled === true && !user.serviceAccountClientId && user.username !== instance.adminUsername.toLowerCase(),
        ).length;
        if (page.length < PAGE) {
          return people;
        }
      }
    }

    async function probeUsers(token) {
      const response = await instance.request.get(
        `${instance.baseUrl}/admin/realms/${encodeURIComponent(instance.realm)}/users?username=${PROBE_USER.username}&exact=true`,
        { headers: bearer(token), timeout: resolveTimeout(REQUEST_MS) },
      );
      expect(response.status(), `${LABEL}: looking the probe user up must succeed`).toBe(200);
      return response.json();
    }

    async function removeProbe() {
      const token = await adminToken();
      for (const user of await probeUsers(token)) {
        const response = await instance.request.delete(`${instance.baseUrl}/admin/realms/${encodeURIComponent(instance.realm)}/users/${user.id}`, {
          headers: bearer(token),
          timeout: resolveTimeout(REQUEST_MS),
        });
        expect([204, 404], `${LABEL}: removing the probe user must succeed`).toContain(response.status());
      }
    }

    test.beforeAll(async ({ browser }) => {
      workspaces.skipUnlessWorkspaces();
      test.setTimeout(resolveTimeout(SETUP_MS));
      expect(
        typeof workspaces.deployToSharedTarget,
        `${LABEL}: workspace-fixture.js must export deployToSharedTarget, which deploys through the workspace's deploy template`,
      ).toBe("function");
      address = await targetAddress();
      own = workspaces.workspaceFixture();
      await workspaces.openWorkspace(shared, browser, own, `${address}:${SSH_PORT},${address}:${HTTPS_PORT}`, LABEL);
      instance = await workspaces.deployToSharedTarget(shared, own, { roles: ["web-app-keycloak"], hostVars: USAGE_HOST_VARS }, LABEL);
    });

    test.afterAll(async () => {
      test.setTimeout(resolveTimeout(CLEANUP_MS));
      if (own && own.context) {
        await workspaces.closeWorkspace(shared, own, LABEL);
      }
    });

    test("usage: apply schedules the daily count", async () => {
      test.setTimeout(resolveTimeout(4 * REQUEST_MS));
      const { project, template } = await usageTemplate();
      expect(workspaces.surveyOf(template), `${LABEL}: the usage template must take no survey`).toEqual([]);
      expect(JSON.parse(template.arguments || "[]"), `${LABEL}: the usage template must take no argument`).toEqual([]);
      workspaces.expectLockedTemplate(template, LABEL);
      const schedules = (await shared.api(own.page, "GET", `/project/${project.id}/schedules`)).filter(
        (schedule) => schedule.template_id === template.id,
      );
      expect(schedules, `${LABEL}: apply must leave exactly one schedule on the usage template`).toHaveLength(1);
      expect(schedules[0].active, `${LABEL}: the usage schedule must be active`).toBe(true);
      expect(schedules[0].cron_format, `${LABEL}: the usage schedule must run once a day`).toMatch(DAILY);
    });

    test("usage: counts the active people of the instance", async () => {
      test.setTimeout(resolveTimeout(3 * USAGE_RUN_MS + 10 * REQUEST_MS));
      await removeProbe();
      const before = await countedPeople();
      expect(before, `${LABEL}: the count must equal the enabled people of the instance`).toBe(await enabledPeople());
      try {
        const token = await adminToken();
        const created = await instance.request.post(`${instance.baseUrl}/admin/realms/${encodeURIComponent(instance.realm)}/users`, {
          headers: { ...bearer(token), "Content-Type": "application/json" },
          data: { ...PROBE_USER, enabled: true },
          timeout: resolveTimeout(REQUEST_MS),
        });
        expect(created.status(), `${LABEL}: the administrator must create the probe user`).toBe(201);
        const probeId = created.headers()["location"].split("/").pop();
        expect(await countedPeople(), `${LABEL}: the count must rise by the probe user`).toBe(before + 1);
        const disabled = await instance.request.put(
          `${instance.baseUrl}/admin/realms/${encodeURIComponent(instance.realm)}/users/${probeId}`,
          { headers: { ...bearer(await adminToken()), "Content-Type": "application/json" }, data: { enabled: false }, timeout: resolveTimeout(REQUEST_MS) },
        );
        expect(disabled.status(), `${LABEL}: the administrator must disable the probe user`).toBe(204);
        expect(await countedPeople(), `${LABEL}: the count must fall back once the probe user is disabled`).toBe(before);
      } finally {
        await removeProbe();
      }
    });
  });
};
