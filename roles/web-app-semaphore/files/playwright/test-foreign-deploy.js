const dns = require("node:dns");
const net = require("node:net");
const { test, expect, chromium } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { gotoOnion, requireDotenvValue } = require("./personas");
const { ANSI } = require("./personas/utils/workspace");

const SETUP_MS = 5 * 60_000;
const DEPLOY_RUN_MS = 60 * 60_000;
const TARGET_ANSWER_MS = 5 * 60_000;
const TARGET_REQUEST_MS = 30_000;
const TARGET_PROBE_MS = 30_000;
const HTTPS_PORT = 443;
const UNCLAIMED_TARGET = "ECONNREFUSED";
const ANSWER_STATUSES = [200, 403];
const PLAY_RECAP_HOST = /^(\S+)\s+:\s+ok=\d+/;

/**
 * Return the boolean a dotenv flag carries, failing unless it is "true" or "false".
 *
 * Args:
 *   raw: the raw value of the variable.
 *   name: the variable name the error names.
 */
function strictFlag(raw, name) {
  const value = requireDotenvValue(raw, name);
  if (value !== "true" && value !== "false") {
    throw new Error(`${name} must be "true" or "false", got ${JSON.stringify(value)}`);
  }
  return value === "true";
}

const deployProjectName = requireDotenvValue(process.env.SEMAPHORE_DEPLOY_PROJECT_NAME, "SEMAPHORE_DEPLOY_PROJECT_NAME");
const deployTemplateName = requireDotenvValue(process.env.SEMAPHORE_DEPLOY_TEMPLATE_NAME, "SEMAPHORE_DEPLOY_TEMPLATE_NAME");
const targetHost = requireDotenvValue(process.env.SEMAPHORE_DEPLOY_TARGET_HOST, "SEMAPHORE_DEPLOY_TARGET_HOST");

exports.register = function (shared) {
  const label = "administrator-deploy";

  /**
   * Return the IPv4 address the shared target resolves to from this container.
   */
  async function targetAddress() {
    try {
      return (await dns.promises.lookup(targetHost, { family: 4 })).address;
    } catch (error) {
      throw new Error(`${label}: the Playwright container cannot resolve the shared target "${targetHost}": ${error.message}`, {
        cause: error,
      });
    }
  }

  /**
   * Return "open" when the HTTPS port of `address` accepts a connection, the
   * socket error code otherwise.
   *
   * Args:
   *   address: the address of the shared target.
   */
  function httpsPortState(address) {
    return new Promise((resolve) => {
      const socket = net.connect({ host: address, port: HTTPS_PORT });
      socket.setTimeout(resolveTimeout(TARGET_PROBE_MS));
      socket.once("connect", () => {
        socket.destroy();
        resolve("open");
      });
      socket.once("timeout", () => {
        socket.destroy();
        resolve("ETIMEDOUT");
      });
      socket.once("error", (error) => resolve(error.code));
    });
  }

  /**
   * Return the foreign-server deploy project and its deploy template as the
   * signed-in administrator sees them.
   *
   * Args:
   *   page: a Playwright page carrying the administrator session.
   */
  async function deployTemplate(page) {
    const projects = await shared.api(page, "GET", "/projects");
    const project = projects.find((candidate) => candidate.name === deployProjectName);
    expect(
      project,
      `${label}: the administrator must see the "${deployProjectName}" project (sees: ${projects.map((candidate) => candidate.name).join(", ")})`,
    ).toBeTruthy();
    const templates = await shared.api(page, "GET", `/project/${project.id}/templates`);
    const template = templates.find((candidate) => candidate.name === deployTemplateName);
    expect(
      template,
      `${label}: the "${deployProjectName}" project must hold the template "${deployTemplateName}" (holds: ${templates.map((candidate) => candidate.name).join(", ")})`,
    ).toBeTruthy();
    return { project, template };
  }

  /**
   * Open the deployed application in a browser that resolves its domain to
   * the shared target and require the answer of its vhost.
   *
   * Args:
   *   address: the address of the shared target.
   *   targetUrl: the URL of the deployed application.
   */
  async function assertTargetAnswers(address, targetUrl) {
    const browser = await chromium.launch({ args: [`--host-resolver-rules=MAP ${targetUrl.hostname} ${address}`] });
    try {
      const context = await browser.newContext({ ignoreHTTPSErrors: true });
      const page = await context.newPage();
      let response;
      await expect
        .poll(
          async () => {
            try {
              response = await gotoOnion(page, targetUrl.href, {
                waitUntil: "domcontentloaded",
                timeout: resolveTimeout(TARGET_REQUEST_MS),
              });
              return response.status();
            } catch (error) {
              return String(error.message).split("\n")[0];
            }
          },
          {
            timeout: resolveTimeout(TARGET_ANSWER_MS),
            intervals: [5_000],
            message: `${label}: ${targetUrl.href} must answer from the shared target "${targetHost}" (${address}) after the deploy`,
          },
        )
        .toEqual(expect.any(Number));
      expect(ANSWER_STATUSES, `${label}: ${targetUrl.href} on the shared target answered HTTP ${response.status()}`).toContain(
        response.status(),
      );
      const headers = response.headers();
      expect(headers["content-type"], `${label}: ${targetUrl.href} on the shared target must answer with HTML`).toContain(
        "text/html",
      );
      expect(
        headers["content-security-policy"],
        `${label}: the deployed vhost of ${targetUrl.hostname} must emit its Content-Security-Policy`,
      ).toBeTruthy();
    } finally {
      await browser.close().catch(() => {});
    }
  }

  test("administrator: the foreign-server deploy template deploys onto the shared target and the deployed application answers there", async ({
    page,
  }) => {
    const deployEnabled = strictFlag(process.env.SEMAPHORE_DEPLOY_ENABLED, "SEMAPHORE_DEPLOY_ENABLED");
    const updatePass = strictFlag(process.env.DEPLOY_IS_UPDATE, "DEPLOY_IS_UPDATE");
    test.skip(!deployEnabled, "SEMAPHORE_DEPLOY_ENABLED=false: the inventory declares no services.semaphore.deploy");
    test.skip(
      updatePass,
      "DEPLOY_IS_UPDATE=true: the shared target is reset once per round, before the first pass, whose run of this scenario claimed it",
    );
    shared.skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(SETUP_MS + DEPLOY_RUN_MS + TARGET_ANSWER_MS));
    const platformHost = requireDotenvValue(process.env.SEMAPHORE_WORKSPACES_PLATFORM_HOST, "SEMAPHORE_WORKSPACES_PLATFORM_HOST");

    await shared.signInPrimary(page, shared.env.adminUsername, shared.env.adminPassword, label);
    const { project, template } = await deployTemplate(page);
    const address = await targetAddress();
    expect(
      await httpsPortState(address),
      `${label}: port ${HTTPS_PORT} of the shared target "${targetHost}" (${address}) must refuse before the deploy. ` +
        "An open port means a deploy or replay used the target since its last reset (run make compose-target-reset); " +
        "any other code means this container cannot reach the target",
    ).toBe(UNCLAIMED_TARGET);

    let taskId;
    try {
      taskId = await shared.runTemplateFromUi(page, project.id, template, label);
      await shared.awaitTaskSuccess(page, project.id, taskId, DEPLOY_RUN_MS, label);
      const output = await shared.api(page, "GET", `/project/${project.id}/tasks/${taskId}/output`);
      const recapHosts = [
        ...new Set(
          output
            .map((entry) => entry.output.replace(ANSI, "").trim().match(PLAY_RECAP_HOST))
            .filter(Boolean)
            .map((match) => match[1]),
        ),
      ];
      expect(recapHosts, `${label}: the deploy of devices.yml must run on the shared target "${targetHost}"`).toContain(targetHost);
      expect(
        recapHosts,
        `${label}: the deploy of devices.yml must never reach the platform host "${platformHost}" of workspaces.yml`,
      ).not.toContain(platformHost);
    } finally {
      if (taskId !== undefined) {
        await shared
          .stopUnfinishedTask(page, project.id, taskId)
          .catch((error) => console.warn(`Cleanup stop of task ${taskId} failed: ${error}`));
      }
    }
    await assertTargetAnswers(
      address,
      new URL(requireDotenvValue(process.env.SEMAPHORE_DEPLOY_TARGET_URL, "SEMAPHORE_DEPLOY_TARGET_URL")),
    );

    await shared.logout(page, label);
  });
};
