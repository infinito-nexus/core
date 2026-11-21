const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const SIGN_IN_MS = 2 * 60_000;
const REFUSED_STATUSES = [403, 404];

exports.register = function (shared) {
  const label = "biber-user";
  const adminLabel = "administrator-app-control";
  const target = shared.env.appControlTargetId;

  /**
   * Return the app-control project and the stop and start templates of the
   * controlled application as the administrator sees them.
   *
   * Args:
   *   browser: the Playwright browser, used for an isolated administrator context.
   */
  async function appControlAsAdministrator(browser) {
    const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
    try {
      const page = await ctx.newPage();
      await page.setViewportSize({ width: 1440, height: 1100 });
      await shared.signInPrimary(page, shared.env.adminUsername, shared.env.adminPassword, adminLabel);
      const project = await shared.awaitAppControlProject(page, true, adminLabel);
      const templates = await shared.appControlTemplates(page, project.id, target);
      await shared.logout(page, adminLabel);
      return { project, templates };
    } finally {
      await ctx.close().catch(() => {});
    }
  }

  test("biber: without the operator role a user-group member neither sees the app-control project nor runs its stop and start templates", async ({
    browser,
  }) => {
    shared.skipUnlessServiceEnabled("ldap");
    test.setTimeout(resolveTimeout(2 * SIGN_IN_MS + shared.RBAC_SYNC_CONVERGENCE_MS));

    const { project, templates } = await appControlAsAdministrator(browser);

    await shared.withBiberInRoleGroup(browser, "user", async () => {
      const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        const page = await ctx.newPage();
        await page.setViewportSize({ width: 1440, height: 1100 });
        await shared.signInPrimary(page, shared.env.biberUsername, shared.env.biberPassword, label);
        await shared.awaitAppControlProject(page, false, label);

        const listing = await shared.apiResponse(page, "GET", `/project/${project.id}/templates`);
        expect(
          REFUSED_STATUSES,
          `${label}: Semaphore must refuse listing the templates of "${shared.env.projectName}" (HTTP ${listing.status()})`,
        ).toContain(listing.status());

        for (const template of [templates.stop, templates.start]) {
          const run = await shared.apiResponse(page, "POST", `/project/${project.id}/tasks`, {
            template_id: template.id,
          });
          expect(
            REFUSED_STATUSES,
            `${label}: Semaphore must refuse running "${template.name}" (HTTP ${run.status()})`,
          ).toContain(run.status());
        }

        await shared.logout(page, label);
      } finally {
        await ctx.close().catch(() => {});
      }
    });
  });
};
