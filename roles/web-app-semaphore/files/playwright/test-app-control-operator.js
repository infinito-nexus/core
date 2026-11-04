const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { apiGetOnion, gotoOnion } = require("./personas");

const SIGN_IN_MS = 2 * 60_000;
const TARGET_ANSWER_MS = 5 * 60_000;
const PAUSED_STATUS = 503;

exports.register = function (shared) {
  const label = "biber-operator";
  const target = shared.env.appControlTargetId;
  const targetUrl = `${shared.env.appControlTargetUrl}/`;
  const language = shared.env.pausedLanguage;

  /**
   * Return the HTTP status the controlled application answers its front page with.
   *
   * Args:
   *   request: an APIRequestContext.
   */
  async function targetStatus(request) {
    const response = await apiGetOnion(request, targetUrl, {
      failOnStatusCode: false,
      maxRedirects: 0,
      timeout: resolveTimeout(30_000),
    });
    return response.status();
  }

  /**
   * Wait until the controlled application answers without a server error and
   * return the status of that answer.
   *
   * Args:
   *   request: an APIRequestContext.
   *   moment: when the answer is expected, for the assertion message.
   */
  async function awaitTargetAnswering(request, moment) {
    let status;
    await expect
      .poll(
        async () => {
          status = await targetStatus(request);
          return status;
        },
        {
          timeout: resolveTimeout(TARGET_ANSWER_MS),
          intervals: [5_000],
          message: `${label}: ${target} must answer ${targetUrl} without a server error ${moment}`,
        },
      )
      .toBeLessThan(500);
    return status;
  }

  /**
   * Open the controlled application in a fresh browser context that asks for
   * the paused-page language and assert the localized paused page.
   *
   * Args:
   *   browser: the Playwright browser.
   */
  async function assertPausedPage(browser) {
    const texts = shared.env.pausedCatalogue[language];
    expect(
      texts,
      `the core catalogs must translate the paused page into "${language}" (translated: ${Object.keys(shared.env.pausedCatalogue).join(", ")})`,
    ).toBeTruthy();
    const visitor = await browser.newContext({
      ignoreHTTPSErrors: true,
      locale: language,
      extraHTTPHeaders: { "Accept-Language": language },
    });
    try {
      const page = await visitor.newPage();
      const response = await gotoOnion(page, targetUrl, { waitUntil: "domcontentloaded" });
      expect(response, `${label}: ${targetUrl} must answer while ${target} is paused`).toBeTruthy();
      expect(response.status(), `${label}: a paused ${target} must answer ${targetUrl} with HTTP ${PAUSED_STATUS}`).toBe(
        PAUSED_STATUS,
      );
      await expect(page.locator("html"), `${label}: nginx must serve the "${language}" paused page`).toHaveAttribute(
        "lang",
        language,
      );
      await expect(page).toHaveTitle(texts.title);
      await expect(page.locator("main h1"), `${label}: the paused heading in "${language}"`).toHaveText(texts.heading);
      await expect(page.locator("main > p"), `${label}: the paused notice in "${language}"`).toHaveText(texts.notice);
      await expect(
        page.locator("main dl dd"),
        `${label}: the paused page must list every contact channel of service_provider.contact`,
      ).toHaveText(shared.env.pausedContacts);
      const beaver = page.locator("svg.scene .beaver");
      await expect(beaver, `${label}: the paused page must show the sleeping beaver`).toBeVisible();
      await expect
        .poll(() => beaver.evaluate((node) => getComputedStyle(node).animationName), {
          message: `${label}: the sleeping beaver must be animated`,
        })
        .not.toBe("none");
    } finally {
      await visitor.close().catch(() => {});
    }
  }

  /**
   * Bring the controlled application back after a failed run left it paused.
   *
   * Args:
   *   page: the page carrying the operator session.
   *   projectId: the id of the app-control project.
   *   templateId: the id of the start template of the controlled application.
   */
  async function resumeTarget(page, projectId, templateId) {
    let timer;
    const deadline = new Promise((_, reject) => {
      timer = setTimeout(
        () => reject(new Error(`resuming ${target} exceeded its deadline`)),
        resolveTimeout(shared.TASK_RUN_MS),
      );
    });
    const resumed = (async () => {
      const task = await shared.api(page, "POST", `/project/${projectId}/tasks`, { template_id: templateId });
      await shared.awaitTaskSuccess(page, projectId, task.id, shared.TASK_RUN_MS, `${label}-cleanup`);
    })();
    try {
      await Promise.race([resumed, deadline]);
    } finally {
      clearTimeout(timer);
    }
  }

  test("biber: as an operator member, stop pauses the controlled app behind the localized paused page and start brings it back", async ({
    browser,
  }) => {
    shared.skipUnlessServiceEnabled("ldap");
    test.setTimeout(
      resolveTimeout(SIGN_IN_MS + shared.RBAC_SYNC_CONVERGENCE_MS + 2 * shared.TASK_RUN_MS + 2 * TARGET_ANSWER_MS),
    );

    await shared.withBiberInRoleGroup(browser, "operator", async () => {
      const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
      let page;
      let project;
      let templates;
      let paused = false;
      try {
        page = await ctx.newPage();
        await page.setViewportSize({ width: 1440, height: 1100 });
        await shared.signInPrimary(page, shared.env.biberUsername, shared.env.biberPassword, label);
        project = await shared.awaitAppControlProject(page, true, label);
        templates = await shared.appControlTemplates(page, project.id, target);
        await awaitTargetAnswering(ctx.request, "before the stop");

        paused = true;
        const stopTask = await shared.runTemplateFromUi(page, project.id, templates.stop, label);
        await shared.awaitTaskSuccess(page, project.id, stopTask, shared.TASK_RUN_MS, label);
        await assertPausedPage(browser);

        const startTask = await shared.runTemplateFromUi(page, project.id, templates.start, label);
        await shared.awaitTaskSuccess(page, project.id, startTask, shared.TASK_RUN_MS, label);
        paused = false;
        expect(
          await awaitTargetAnswering(ctx.request, "after the start"),
          `${label}: a resumed ${target} must no longer serve the paused page`,
        ).not.toBe(PAUSED_STATUS);

        await shared.logout(page, label);
      } finally {
        if (paused) {
          await resumeTarget(page, project.id, templates.start.id).catch((error) =>
            console.warn(`Cleanup start of ${target} failed: ${error}`),
          );
        }
        await ctx.close().catch(() => {});
      }
    });
  });
};
