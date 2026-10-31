const { test, expect } = require("@playwright/test");
const { gotoOnion, performKeycloakLoginForm } = require("./personas");
const { resolveTimeout } = require("./timeouts");

const REVIEW_ROUTE = "ci-review";
const REVIEW_SET = "Crossposter review";
const REVIEW_TAG = "crossposterreview";

async function routeReview(page, shared, headers, target) {
  const sets = await shared.apiRequest(page, headers, "GET", `/social-sets?workspace_id=${target.workspace}`);
  const reviewSet = (sets || []).find((item) => item.name === REVIEW_SET);
  expect(reviewSet, `the deploy must create the "${REVIEW_SET}" social set`).toBeTruthy();
  await shared.apiRequest(page, headers, "PUT", `/social-sets/${reviewSet.id}`, {
    name: reviewSet.name,
    is_default: Boolean(reviewSet.is_default),
    accounts: [{ social_account_id: target.account, default_settings: {} }],
  });
  return target.workspace;
}

async function postOnMastodon(page, shared, text, label) {
  await gotoOnion(page, `${shared.env.mastodonBaseUrl}/auth/sign_in`, { waitUntil: "domcontentloaded" });
  await page.getByRole("link", { name: /sso|single sign-on/i }).click();
  await page.waitForLoadState("domcontentloaded");
  if (page.url().includes(`${shared.env.oidcIssuerUrl}/protocol/openid-connect/auth`)) {
    await performKeycloakLoginForm(page, shared.env.adminUsername, shared.env.adminPassword);
  }
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: `${label}: expected Mastodon's home timeline` })
    .not.toContain("/auth/sign_in");
  await gotoOnion(page, `${shared.env.mastodonBaseUrl}/home`, { waitUntil: "domcontentloaded" });
  const token = await page.evaluate(() => JSON.parse(document.getElementById("initial-state").textContent).meta.access_token);
  expect(token, `${label}: Mastodon's web client must hold a session token`).toBeTruthy();
  const response = await page.request.post(`${shared.env.mastodonBaseUrl}/api/v1/statuses`, {
    headers: { Authorization: `Bearer ${token}` },
    form: { status: text, visibility: "public" },
  });
  expect(response.ok(), `${label}: Mastodon must accept the status, got HTTP ${response.status()}`).toBeTruthy();
}

async function crosspostedDraft(page, shared, headers, workspace, marker) {
  const drafts = await shared.apiRequest(
    page,
    headers,
    "GET",
    `/publications?workspace_id=${workspace}&status=draft&search=${encodeURIComponent(marker)}&limit=10`,
  );
  return (drafts || []).find((item) => (item.metadata || {}).crossposter_route === REVIEW_ROUTE) || null;
}

async function awaitCrosspostedDraft(page, shared, headers, workspace, marker, label) {
  let draft = null;
  await expect
    .poll(
      async () => {
        draft = await crosspostedDraft(page, shared, headers, workspace, marker);
        return Boolean(draft);
      },
      { timeout: resolveTimeout(180_000), message: `${label}: the crossposter must turn the status into a review draft` },
    )
    .toBe(true);
  return draft;
}

async function openDraftInDesk(page, shared, marker, label) {
  await gotoOnion(page, `${shared.env.appBaseUrl}/publications?tab=drafts`, { waitUntil: "domcontentloaded" });
  await page.getByRole("textbox", { name: /search posts/i }).fill(marker);
  const listed = page.getByRole("link", { name: new RegExp(marker, "i") }).first();
  await expect(listed, `${label}: the crossposted draft must be listed among the drafts`).toBeVisible({
    timeout: resolveTimeout(60_000),
  });
  await listed.click();
  const text = page.getByRole("textbox", { name: /post text/i }).first();
  await expect(text, `${label}: the draft must open in the composer`).toBeVisible({ timeout: resolveTimeout(60_000) });
  return text;
}

exports.REVIEW_TAG = REVIEW_TAG;
exports.routeReview = routeReview;
exports.postOnMastodon = postOnMastodon;
exports.awaitCrosspostedDraft = awaitCrosspostedDraft;
exports.openDraftInDesk = openDraftInDesk;

exports.register = function (shared) {
  test("administrator: finds a crossposted draft in the desk, edits it and schedules it", async ({ page }) => {
    shared.skipUnlessServiceEnabled("crossposter");
    shared.skipUnlessServiceEnabled("mastodon");
    shared.skipOnOnionSibling("mastodon");
    test.setTimeout(resolveTimeout(420_000)); // Mastodon sign-in, the crossposter's poll interval, composer autosave and scheduling
    const label = "administrator";
    const marker = `cp-desk-${Date.now()}`;
    const edited = `Edited in the desk ${marker}`;

    await shared.signInViaLocal(page, shared.env.breakglassEmail, shared.env.breakglassPassword, label);
    const headers = shared.apiSession();
    const workspace = await routeReview(page, shared, headers, await shared.apiAccount(page, headers, "mastodon"));
    await postOnMastodon(page, shared, `Desk review ${marker} #${REVIEW_TAG}`, label);
    const draft = await awaitCrosspostedDraft(page, shared, headers, workspace, marker, label);
    const text = await openDraftInDesk(page, shared, marker, label);
    await text.fill(edited);
    await page.getByRole("main").getByRole("button", { name: /^more$/i }).click();
    await page.getByRole("menuitem", { name: /^schedule$/i }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("button", { name: /^in 3 hours$/i }).click();
    await dialog.getByRole("button", { name: /^schedule$/i }).click();

    await expect
      .poll(
        async () => {
          const current = await shared.apiRequest(page, headers, "GET", `/publications/${draft.id}`);
          return `${current.status}|${String(current.source_text).includes(edited)}`;
        },
        { timeout: resolveTimeout(60_000), message: `${label}: the edited draft must end scheduled` },
      )
      .toBe("scheduled|true");
    await shared.logout(page, label);
  });
};
