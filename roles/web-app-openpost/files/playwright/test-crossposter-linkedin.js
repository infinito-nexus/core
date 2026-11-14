const { test, expect } = require("@playwright/test");
const { gotoOnion } = require("./personas");
const { resolveTimeout } = require("./timeouts");
const { REVIEW_TAG, routeReview, postOnMastodon, awaitCrosspostedDraft, openDraftInDesk } = require("./test-crossposter-draft");

const LINKEDIN_ORIGIN = "https://www.linkedin.com";

async function routeLinkedInToFake(page, shared) {
  await page.route(`${LINKEDIN_ORIGIN}/**`, async (route) => {
    const target = new URL(route.request().url());
    const response = await route.fetch({ url: `${shared.env.linkedinFakeUrl}${target.pathname}${target.search}`, maxRedirects: 0 });
    await route.fulfill({ response });
  });
}

async function signUpOnLinkedIn(page, member, label) {
  await gotoOnion(page, `${LINKEDIN_ORIGIN}/signup`, { waitUntil: "domcontentloaded" });
  await page.getByLabel("Name").fill(member.name);
  await page.getByLabel("Email").fill(member.email);
  await page.getByLabel("Password").fill(member.password);
  await page.getByRole("button", { name: /^create account$/i }).click();
  await expect(page.getByText(/your account is ready/i), `${label}: the fake LinkedIn must create the member`).toBeVisible({
    timeout: resolveTimeout(30_000),
  });
}

async function linkedInAccountIds(page, shared, headers, workspace) {
  const accounts = await shared.apiRequest(page, headers, "GET", `/accounts?workspace_id=${workspace}`);
  return accounts.filter((item) => item.platform === "linkedin").map((item) => item.id);
}

async function connectLinkedIn(page, shared, headers, workspace, member, label) {
  const known = await linkedInAccountIds(page, shared, headers, workspace);
  const { url } = await shared.apiRequest(page, headers, "GET", `/accounts/linkedin/auth-url?workspace_id=${workspace}`);
  await gotoOnion(page, url, { waitUntil: "domcontentloaded" });
  await page.getByLabel("Email").fill(member.email);
  await page.getByLabel("Password").fill(member.password);
  await page.getByRole("button", { name: /^allow$/i }).click();
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: `${label}: OpenPost must finish the LinkedIn callback` })
    .not.toMatch(/linkedin\.com|\/accounts\/linkedin\/callback/);
  expect(page.url(), `${label}: OpenPost must accept the LinkedIn consent`).not.toContain("failed");
  const selection = new URL(page.url()).searchParams.get("connection_id");
  if (selection) {
    const offer = await shared.apiRequest(page, headers, "GET", `/accounts/selections/${selection}`);
    const options = (offer.options || []).map((option) => String(option.id));
    expect(options.length, `${label}: LinkedIn must offer the member profile`).toBeGreaterThan(0);
    await shared.apiRequest(page, headers, "POST", `/accounts/selections/${selection}/complete`, {
      selection_ids: [options.find((id) => id.startsWith("person:")) || options[0]],
    });
  }
  let added = [];
  await expect
    .poll(
      async () => {
        added = (await linkedInAccountIds(page, shared, headers, workspace)).filter((id) => !known.includes(id));
        return added.length;
      },
      { timeout: resolveTimeout(30_000), message: `${label}: the LinkedIn member must be connected in the review workspace` },
    )
    .toBe(1);
  return { workspace, account: added[0] };
}

async function publishInDesk(page, label) {
  await page.getByRole("main").getByRole("button", { name: /^more$/i }).click();
  await page.getByRole("menuitem", { name: /^publish now$/i }).click();
  const confirm = page.getByRole("alertdialog").or(page.getByRole("dialog"));
  if (await confirm.first().isVisible().catch(() => false)) {
    await confirm.first().getByRole("button", { name: /publish/i }).first().click();
  }
  await expect(confirm.first(), `${label}: the publish confirmation must close`).toBeHidden({ timeout: resolveTimeout(30_000) });
}

exports.register = function (shared) {
  test("administrator: a Mastodon status becomes a review draft, is edited in the desk and lands on LinkedIn", async ({ page }) => {
    shared.skipUnlessServiceEnabled("crossposter");
    shared.skipUnlessServiceEnabled("mastodon");
    shared.skipUnlessServiceEnabled("provider");
    shared.skipOnOnionSibling("mastodon");
    test.skip(
      shared.env.appBaseUrl.includes(".onion"),
      "LinkedIn cannot redirect a member back to an onion OpenPost origin",
    );
    test.setTimeout(resolveTimeout(480_000)); // fake sign-up and consent, Mastodon sign-in, the crossposter's poll interval and the publishing worker
    const label = "administrator";
    const stamp = Date.now();
    const marker = `cp-linkedin-${stamp}`;
    const edited = `Edited for LinkedIn ${marker}`;
    const member = {
      name: `Desk Pilot ${stamp}`,
      email: `desk-pilot-${stamp}@linkedin.invalid`,
      password: `fake-${stamp}-linkedin`,
    };

    await routeLinkedInToFake(page, shared);
    await signUpOnLinkedIn(page, member, label);
    await shared.signInViaLocal(page, shared.env.breakglassEmail, shared.env.breakglassPassword, label);
    const headers = shared.apiSession();
    const { workspace } = await shared.apiAccount(page, headers, "mastodon");
    const target = await connectLinkedIn(page, shared, headers, workspace, member, label);
    await routeReview(page, shared, headers, target);
    await postOnMastodon(page, shared, `LinkedIn review ${marker} #${REVIEW_TAG}`, label);
    const draft = await awaitCrosspostedDraft(page, shared, headers, workspace, marker, label);

    const text = await openDraftInDesk(page, shared, marker, label);
    await text.fill(edited);
    await expect
      .poll(
        async () => String((await shared.apiRequest(page, headers, "GET", `/publications/${draft.id}`)).source_text).includes(edited),
        { timeout: resolveTimeout(60_000), message: `${label}: the desk must save the edited text` },
      )
      .toBe(true);
    await publishInDesk(page, label);

    let rendition = {};
    await expect
      .poll(
        async () => {
          const current = await shared.apiRequest(page, headers, "GET", `/publications/${draft.id}`);
          rendition = (current.renditions || []).find((item) => item.social_account_id === target.account) || {};
          return rendition.status;
        },
        { timeout: resolveTimeout(180_000), message: `${label}: the LinkedIn destination must end published` },
      )
      .toBe("published");
    expect(rendition.external_id, `${label}: OpenPost must record the id of the LinkedIn post`).toMatch(/^urn:li:share:/);

    await gotoOnion(page, `${LINKEDIN_ORIGIN}/feed/update/${rendition.external_id}`, { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("article"), `${label}: the LinkedIn post must show the text edited in the desk`).toContainText(edited);
    await expect(page, `${label}: the LinkedIn post must carry the member's name`).toHaveTitle(new RegExp(member.name));

    const posts = await (await page.request.get(`${shared.env.linkedinFakeUrl}/__fake/linkedin/posts`)).json();
    const delivered = posts.filter((post) => String(post.text).includes(marker));
    expect(delivered.map((post) => post.text), `${label}: LinkedIn must receive the edited post exactly once`).toEqual([edited]);
    expect(rendition.external_id, `${label}: OpenPost must record the post LinkedIn created`).toBe(delivered[0].id);

    await gotoOnion(page, `${shared.env.appBaseUrl}/publications`, { waitUntil: "domcontentloaded" });
    await shared.logout(page, label);
  });
};
