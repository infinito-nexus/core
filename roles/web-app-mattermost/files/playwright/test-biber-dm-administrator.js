const { test, expect } = require("@playwright/test");

const { performKeycloakLoginForm } = require("./personas");

exports.register = function (shared) {
  test("mattermost: biber sends direct message to administrator, administrator receives it", async ({ browser }) => {
    test.skip(!shared.oidcEnabled, "OIDC shared service disabled");

    const oidcAuthUrl = shared.expectedOidcAuthUrl();
    const baseUrl = shared.expectedMattermostBaseUrl();
    const testMessage = `Playwright test ${Date.now()}`;

    const biberContext = await browser.newContext({ ignoreHTTPSErrors: true });
    const adminContext = await browser.newContext({ ignoreHTTPSErrors: true });

    try {
      const biberPage = await biberContext.newPage();

      await shared.startMattermostSsoFlow(biberPage, baseUrl);
      await expect
        .poll(() => biberPage.url(), {
          timeout: 30_000,
          message: `Expected redirect to Keycloak OIDC: ${oidcAuthUrl}`,
        })
        .toContain(oidcAuthUrl);

      await performKeycloakLoginForm(biberPage, shared.env.biberUsername, shared.env.biberPassword);

      await expect
        .poll(() => biberPage.url(), {
          timeout: 60_000,
          message: "Expected redirect back to Mattermost after biber login",
        })
        .toContain(baseUrl);

      await shared.dismissMattermostPopups(biberPage);

      // /{team}/messages/@{username} auto-joins the open team and opens the DM
      // in one step, dodging /select_team on first login.
      await biberPage.goto(`${baseUrl}/main/messages/@${shared.env.adminUsername}`);

      await shared.dismissMattermostPopups(biberPage);

      const messageInput = biberPage
        .locator("#post_textbox, [data-testid='post_textbox'], div[contenteditable='true'].post-create__input")
        .first();
      await messageInput.waitFor({ state: "visible", timeout: 30_000 });
      await messageInput.click({ force: true });
      // keyboard.type() bypasses fill()'s contenteditable-skipping React onChange gap.
      await biberPage.keyboard.type(testMessage);
      await biberPage.keyboard.press("Enter");

      await expect(
        biberPage.getByTestId("postContent").getByText(testMessage)
      ).toBeVisible({ timeout: 15_000 });

      await shared.mattermostLogout(biberPage, baseUrl);

      const adminPage = await adminContext.newPage();

      await shared.startMattermostSsoFlow(adminPage, baseUrl);
      await expect
        .poll(() => adminPage.url(), {
          timeout: 30_000,
          message: `Expected redirect to Keycloak OIDC: ${oidcAuthUrl}`,
        })
        .toContain(oidcAuthUrl);

      await performKeycloakLoginForm(adminPage, shared.env.adminUsername, shared.env.adminPassword);

      await expect
        .poll(() => adminPage.url(), {
          timeout: 60_000,
          message: "Expected redirect back to Mattermost after admin login",
        })
        .toContain(baseUrl);

      await shared.dismissMattermostPopups(adminPage);
      await shared.waitForMattermostChannelView(adminPage, 30_000);

      await adminPage.goto(`${baseUrl}/main/messages/@${shared.env.biberUsername}`);

      await expect(
        adminPage.getByTestId("postContent").getByText(testMessage)
      ).toBeVisible({ timeout: 30_000 });

      await shared.mattermostLogout(adminPage, baseUrl);
    } finally {
      await biberContext.close().catch(() => {});
      await adminContext.close().catch(() => {});
    }
  });
};
