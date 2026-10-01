// SeaweedFS object-store scenario for Moodle.
//
// tool_objectfs is a deferred store: an upload lands on the local filedir and
// only moves to S3 when the push_objects_to_storage scheduled task runs, so
// the action uploads a file AND runs that task from the admin UI. It asserts
// the uploaded bytes' own key rather than bucket growth: tool_objectfs writes
// to <h0h1>/<h2h3>/<contenthash>, and Moodle's contenthash is the sha1 of the
// file content.
//
// Required env (rendered by templates/playwright.env.j2):
//   APP_BASE_URL, CANONICAL_DOMAIN, the admin login vars consumed by
//   loginAsSiteAdmin, and the SEAWEEDFS_* keys consumed by
//   runSeaweedfsStorageCheck.

const { createHash, randomBytes } = require("node:crypto");
const { test, expect } = require("@playwright/test");
const { resolveTimeout, isOnionTarget } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const {
  collectBucketObjects,
  gotoOnion,
  runSeaweedfsStorageCheck,
  seaweedfsEnv,
} = require("./personas");

const PUSH_TASK = "tool_objectfs\\task\\push_objects_to_storage";
const TASK_COMPLETE = /Scheduled task complete:.*push_objects_to_storage/;

exports.register = function (shared) {
  test("seaweedfs: an uploaded Moodle file is stored in the SeaweedFS bucket", async ({ page, browser }) => {
    test.skip(
      isOnionTarget(),
      "the SeaweedFS S3 endpoint is an in-cluster http service, not an onion surface, so the bucket cannot be listed from a Tor target",
    );
    skipUnlessServiceEnabled("seaweedfs");
    test.setTimeout(resolveTimeout(600_000));

    const base = shared.env.moodleBaseUrl.replace(/\/$/, "");

    const marker = `infinito-storage-check-${Date.now()}-${randomBytes(4).toString("hex")}`;
    const payload = Buffer.from(`infinito storage check ${marker}`);
    const contenthash = createHash("sha1").update(payload).digest("hex");
    const objectKey = `${contenthash.slice(0, 2)}/${contenthash.slice(2, 4)}/${contenthash}`;

    await runSeaweedfsStorageCheck(page, browser, {
      label: "a Moodle private-files upload pushed by tool_objectfs",
      pollDeadlineMs: resolveTimeout(180_000),
      action: async (appPage) => {
        await shared.loginAsSiteAdmin(appPage);

        await gotoOnion(appPage, `${base}/user/files.php`, {
          waitUntil: "domcontentloaded",
          timeout: resolveTimeout(60_000),
        });

        const addButton = appPage.locator(".fp-btn-add a").first();
        await expect(
          addButton,
          "the private files page must render the file manager's Add button; without it no upload surface exists",
        ).toBeVisible({ timeout: resolveTimeout(60_000) });
        await addButton.click();

        const uploadRepository = appPage
          .locator(".file-picker .fp-repo")
          .filter({ hasText: /upload a file/i })
          .first();
        if (
          await uploadRepository
            .waitFor({ state: "visible", timeout: resolveTimeout(15_000) })
            .then(() => true)
            .catch(() => false)
        ) {
          await uploadRepository.click();
        }

        const fileInput = appPage.locator('input[name="repo_upload_file"]').first();
        await expect(
          fileInput,
          "the file picker's upload repository must expose repo_upload_file; its absence means the Upload a file repository is disabled",
        ).toBeAttached({ timeout: resolveTimeout(60_000) });

        await fileInput.setInputFiles({
          name: `${marker}.txt`,
          mimeType: "text/plain",
          buffer: payload,
        });
        await appPage.locator(".fp-upload-btn").first().click();

        await expect(
          appPage.getByText(marker, { exact: false }).first(),
          `the uploaded file '${marker}.txt' must appear in the Moodle file manager`,
        ).toBeVisible({ timeout: resolveTimeout(60_000) });

        await appPage.locator("#id_submitbutton").first().click();
        await appPage.waitForLoadState("load");

        await gotoOnion(
          appPage,
          `${base}/admin/tool/task/schedule_task.php?task=${encodeURIComponent(PUSH_TASK)}`,
          { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) },
        );

        const runNow = appPage.getByRole("button", { name: /run now/i }).first();
        await expect(
          runNow,
          "the scheduled-task page must offer Run now; its absence means the session is not a Moodle site administrator (schedule_task.php calls require_admin, and the OIDC administrator only reaches that account when its username claim matches), or tool_task/enablerunnow is off, or $CFG->pathtophp does not point at an executable PHP CLI",
        ).toBeVisible({ timeout: resolveTimeout(60_000) });
        await runNow.click();

        await expect(
          appPage.locator("pre.task-output"),
          "the streamed task output must report the push task completing; schedule_task.php opens pre.task-output before it runs the task, so the element alone proves nothing and a failed run reports 'Scheduled task failed' instead",
        ).toContainText(TASK_COMPLETE, { timeout: resolveTimeout(120_000) });
        await appPage.waitForLoadState("load");
      },
    });

    await expect
      .poll(
        async () => (await collectBucketObjects(page.request, seaweedfsEnv())).has(objectKey),
        {
          timeout: resolveTimeout(120_000),
          message:
            `the bucket must hold '${objectKey}', the key tool_objectfs derives from the uploaded file's own content; ` +
            "a bucket that merely grew only proves the task flushed some other backlogged object",
        },
      )
      .toBe(true);
  });
};
