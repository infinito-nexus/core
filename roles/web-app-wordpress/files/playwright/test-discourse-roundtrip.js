const { test, expect } = require("@playwright/test");

const { installCspViolationObserver } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

exports.register = function (shared) {
  test("wordpress post published with discourse toggle appears as a Discourse topic", async ({
    browser,
  }) => {
    skipUnlessServiceEnabled("discourse");
    test.skip(
      !shared.env.discourseApiKey,
      "DISCOURSE_API_KEY not provisioned this run (wp-discourse setup phase did not execute)"
    );
    // 10 min for the end-to-end round-trip: two browser contexts + two
    // OIDC logins (main + cleanup) + WP editor + Discourse polling +
    // post-status cleanup across 5 statuses exceeds the default 300 s
    // budget on cold caches. Per-step timeouts (60 s OIDC, 30 s editor
    // expects, 60 s snackbar, 60 s discourse poll) remain in place to
    // fail fast on real regressions.
    test.setTimeout(600_000);
    const stamp = Date.now();
    const unique = Math.random().toString(36).slice(2, 8);
    const postTitle = `infinito-playwright-discourse-roundtrip-${stamp}-${unique}`;
    const postBodyMarker = `round-trip marker ${stamp}-${unique}`;
    const postBody = `This post verifies the WP -> Discourse pipeline. ${postBodyMarker}`;

    const wpCtx = await browser.newContext({
      ignoreHTTPSErrors: true,
      viewport: { width: 1440, height: 1100 },
    });
    const reqCtx = await browser.newContext({ ignoreHTTPSErrors: true });
    const wpPage = await wpCtx.newPage();
    await installCspViolationObserver(wpPage);

    try {
      await shared.wpAdminLoginViaOidc(
        wpPage,
        shared.env.wpBaseUrl,
        shared.env.adminUsername,
        shared.env.adminPassword
      );

      await wpPage.goto(`${shared.env.wpBaseUrl}/wp-admin/post-new.php`, {
        waitUntil: "domcontentloaded",
      });

      // First-time editor visit shows a "Welcome to the editor" guide
      // modal that hides the title textbox from the accessibility tree.
      // Scope to the dialog and click its Close; a generic /close/i query
      // also matches unrelated buttons in the editor toolbar.
      const welcomeDialog = wpPage.getByRole("dialog", {
        name: /welcome to the editor/i,
      });
      if (
        await welcomeDialog.isVisible({ timeout: 5_000 }).catch(() => false)
      ) {
        await welcomeDialog
          .getByRole("button", { name: /^close$/i })
          .click()
          .catch(async () => {
            await wpPage.keyboard.press("Escape");
          });
      }

      // WP Gutenberg 6.3+ wraps the editor in an iframe; fall back to
      // top-level locators for older versions that don't.
      const editorIframe = wpPage.frameLocator(
        "iframe[name='editor-canvas']",
      );
      const iframedTitleBox = editorIframe
        .getByRole("textbox", { name: /add title/i })
        .first();
      const topLevelTitleBox = wpPage
        .getByRole("textbox", { name: /add title/i })
        .first();
      const titleBox = (await iframedTitleBox
        .isVisible({ timeout: 5_000 })
        .catch(() => false))
        ? iframedTitleBox
        : topLevelTitleBox;
      await expect(titleBox, "Expected the post title editor").toBeVisible({
        timeout: 60_000,
      });
      await titleBox.fill(postTitle);

      // `keyboard.press('Tab')` is unsafe — it can land on WP's command
      // palette trigger and route subsequent typing into the palette
      // search instead of the post body. Pressing Enter at the end of
      // the title block splits a new paragraph below, focused.
      await titleBox.press("Enter");
      await wpPage.keyboard.type(postBody);
      // Defensive: close the command palette if a previous keypress
      // surfaced it so it doesn't intercept later clicks.
      await wpPage.keyboard.press("Escape").catch(() => {});

      // wp-discourse 2.6+ ships a Gutenberg PluginSidebar
      // (name="discourse-sidebar", title="Discourse"). It is a standalone
      // toolbar toggle, not a panel inside the document sidebar. Match
      // by word-boundaries so the OIDC "Login with Discourse" button on
      // /wp-login can't match here (defensive — we are post-login).
      const discourseSidebarToggle = wpPage
        .getByRole("button", { name: /^\s*discourse\s*$/i })
        .first();
      await expect(
        discourseSidebarToggle,
        "Expected the wp-discourse PluginSidebar toolbar toggle"
      ).toBeVisible({ timeout: 30_000 });
      await discourseSidebarToggle.click();

      // The checkbox inside the wp-discourse sidebar carries no
      // aria-label, no name, no id — only a className. Target it
      // directly. Source: wp-content/plugins/wp-discourse/admin/
      // discourse-sidebar/src/index.js
      // (`<input type="checkBox" className="wpdc-publish-topic-checkbox" />`).
      // The plugin persists the choice as the `publish_to_discourse`
      // post-meta on save.
      const publishToggle = wpPage
        .locator("input.wpdc-publish-topic-checkbox")
        .first();
      await expect(
        publishToggle,
        "Expected the wp-discourse 'Publish' checkbox inside the Discourse sidebar"
      ).toBeVisible({ timeout: 30_000 });
      if (!(await publishToggle.isChecked())) {
        await publishToggle.check();
      }

      const publishBtn = wpPage
        .getByRole("button", { name: /^publish$/i })
        .first();
      await publishBtn.click();
      const confirmPublish = wpPage
        .getByRole("button", { name: /^publish$/i })
        .last();
      if ((await confirmPublish.count().catch(() => 0)) > 0) {
        await confirmPublish.click().catch(() => {});
      }

      await expect(
        wpPage.getByText(/post published|entry published/i).first(),
        "Expected the WP 'post published' snackbar"
      ).toBeVisible({ timeout: 60_000 });

      const expectedBodySubstring = postBodyMarker;
      let topic = null;
      const deadline = Date.now() + 60_000;
      while (Date.now() < deadline) {
        topic = await shared.discourseSearchTopicByTitle(reqCtx.request, postTitle);
        if (topic) break;
        await new Promise((r) => setTimeout(r, 3_000));
      }
      expect(
        topic,
        `Expected Discourse topic with title "${postTitle}" to appear after wp-discourse publish`
      ).toBeTruthy();

      const topicResp = await shared.discourseApiRequest(
        reqCtx.request,
        `/t/${topic.id}.json`
      );
      expect(topicResp.ok(), `GET /t/${topic.id}.json must succeed`).toBe(true);
      const topicBody = await topicResp.json();
      const firstPost =
        topicBody?.post_stream?.posts?.[0]?.cooked ||
        topicBody?.post_stream?.posts?.[0]?.raw ||
        "";
      expect(
        firstPost.includes(expectedBodySubstring),
        `Discourse topic first post MUST contain the WP body marker "${expectedBodySubstring}"`
      ).toBe(true);

      await shared.wpSignOut(wpPage, shared.env.wpBaseUrl);
    } finally {
      // Playwright counts the finally block toward the test budget; a
      // hung Trash-link click previously consumed the full 600 s timeout
      // even when every assertion above had passed (the Trash link's
      // post-click `waitForLoadState('domcontentloaded')` hangs on some
      // WP/Gutenberg combos because the move-to-trash is an XHR, not a
      // navigation). Bound the WP-side cleanup to 60 s.
      const wpCleanupBudgetMs = 60_000;
      const wpCleanupDeadline = Date.now() + wpCleanupBudgetMs;
      try {
        const wpPageCleanup = await wpCtx.newPage();
        await Promise.race([
          (async () => {
            await shared.wpAdminLoginViaOidc(
              wpPageCleanup,
              shared.env.wpBaseUrl,
              shared.env.adminUsername,
              shared.env.adminPassword
            ).catch(() => {});
            for (const status of [
              "publish",
              "draft",
              "pending",
              "private",
              "future",
            ]) {
              if (Date.now() >= wpCleanupDeadline) break;
              await wpPageCleanup
                .goto(
                  `${shared.env.wpBaseUrl}/wp-admin/edit.php?post_status=${status}&s=${encodeURIComponent(postTitle)}`,
                  { waitUntil: "domcontentloaded", timeout: 10_000 }
                )
                .catch(() => {});
              const trashLinks = wpPageCleanup.locator(
                `tr:has-text("${postTitle}") a.submitdelete`
              );
              const n = await trashLinks.count().catch(() => 0);
              for (let i = 0; i < n; i += 1) {
                if (Date.now() >= wpCleanupDeadline) break;
                await trashLinks
                  .nth(i)
                  .click()
                  .catch(() => {});
                await wpPageCleanup
                  .waitForLoadState("domcontentloaded", { timeout: 5_000 })
                  .catch(() => {});
              }
            }
            if (Date.now() < wpCleanupDeadline) {
              await wpPageCleanup
                .goto(`${shared.env.wpBaseUrl}/wp-admin/edit.php?post_status=trash`, {
                  waitUntil: "domcontentloaded",
                  timeout: 10_000,
                })
                .catch(() => {});
              const emptyTrash = wpPageCleanup
                .getByRole("button", { name: /empty\s*trash/i })
                .first();
              if ((await emptyTrash.count().catch(() => 0)) > 0) {
                await emptyTrash.click().catch(() => {});
              }
            }
          })(),
          new Promise((resolve) => setTimeout(resolve, wpCleanupBudgetMs)),
        ]);
        await wpPageCleanup.close().catch(() => {});
      } catch (err) {
        console.warn(`WP teardown of "${postTitle}" failed: ${err}`);
      }
      try {
        const topic = await shared.discourseSearchTopicByTitle(
          reqCtx.request,
          postTitle
        );
        if (topic?.id) {
          await shared.discourseDeleteTopic(reqCtx.request, topic.id);
        }
      } catch (err) {
        console.warn(`Discourse teardown of "${postTitle}" failed: ${err}`);
      }
      await wpCtx.close().catch(() => {});
      await reqCtx.close().catch(() => {});
    }
  });
};
