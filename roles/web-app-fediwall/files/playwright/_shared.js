// Shared fediwall Playwright spec state: env vars, login/post helpers for
// the cross-Fediverse posting flow, wall-content assertions, and the
// `beforeEach` env-presence guard. `playwright.spec.js` wires the
// lifecycle hook and `require()`s one test module per scenario so each
const { resolveTimeout } = require("./timeouts");
// test stays atomar.

const { expect } = require("@playwright/test");

const {
  decodeDotenvQuotedValue,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
} = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN || "");
const defaultSlug = decodeDotenvQuotedValue(process.env.FEDIWALL_DEFAULT_SLUG || "");
const wallSlugs = JSON.parse(decodeDotenvQuotedValue(process.env.FEDIWALL_WALL_SLUGS || "[]"));
const mastodonBaseUrl = normalizeBaseUrl(process.env.MASTODON_BASE_URL || "");
const friendicaBaseUrl = normalizeBaseUrl(process.env.FRIENDICA_BASE_URL || "");
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME || "");
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD || "");

async function beforeEach({ page }) {
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  expect(defaultSlug, "FEDIWALL_DEFAULT_SLUG must be set").toBeTruthy();
  await page.context().clearCookies();
}

// Drive Mastodon's OIDC login flow as biber. Lands on the Mastodon home
// timeline once Keycloak redirects back. First-time login auto-creates
// biber's local Mastodon account through the openid_connect plugin.
//
// Mastodon renders the OIDC sign-in button as a Rails-UJS pseudo-form:
//
//   <a class="btn button-openid_connect" data-method="post"
//      href="/auth/auth/openid_connect">…</a>
//
// A plain Playwright click() submits a regular GET, which Mastodon
// answers with HTTP 404 ("redirect endpoint expects POST"). We bypass
// Rails-UJS by building and submitting an actual <form method="post">
// in the page, with the CSRF token Mastodon embedded in <meta>.
async function loginToMastodonViaOidc(page, baseUrl) {
  await page.goto(`${baseUrl}/auth/sign_in`);
  const oidcLink = page.locator("a[href*='/auth/auth/openid_connect'], a[href*='/auth/openid_connect']").first();
  await expect(oidcLink, "Expected Mastodon OIDC sign-in link").toBeVisible({ timeout: resolveTimeout(30_000) });

  await Promise.all([
    // eslint-disable-next-line playwright/no-wait-for-navigation -- the navigation target depends on the OIDC issuer; waitForURL would need a runtime-built pattern. The Promise.all is the documented Playwright pattern for "click triggers navigation".
    page.waitForNavigation({ waitUntil: "domcontentloaded" }),
    page.evaluate(() => {
      const a = document.querySelector(
        "a[href*='/auth/auth/openid_connect'], a[href*='/auth/openid_connect']"
      );
      if (!a) throw new Error("OIDC sign-in anchor disappeared before submit");
      const csrfMeta = document.querySelector("meta[name='csrf-token']");
      const csrfParamMeta = document.querySelector("meta[name='csrf-param']");
      const form = document.createElement("form");
      form.method = "POST";
      form.action = a.getAttribute("href");
      if (csrfMeta && csrfParamMeta) {
        const tokenInput = document.createElement("input");
        tokenInput.type = "hidden";
        tokenInput.name = csrfParamMeta.getAttribute("content");
        tokenInput.value = csrfMeta.getAttribute("content");
        form.appendChild(tokenInput);
      }
      document.body.appendChild(form);
      form.submit();
    }),
  ]);

  await performKeycloakLoginForm(page, biberUsername, biberPassword);

  // First-time OIDC login on Mastodon 4.x renders a "Profile setup"
  // wizard (display name + bio + discoverability) modally over the
  // home column. Playwright's compose-textarea click is intercepted
  // by the modal layer, so dismiss the wizard via "Save and continue"
  // when it appears. The wizard does not appear on subsequent logins.
  const saveAndContinue = page
    .locator("button[type='submit'], button")
    .filter({ hasText: /save and continue/i })
    .first();
  if (await saveAndContinue.isVisible({ timeout: resolveTimeout(10_000) }).catch(() => false)) {
    await saveAndContinue.click();
  }

  // The compose textarea sits at the top of the home column. Mastodon
  // 4.x uses the placeholder "What's on your mind?" — match on the
  // distinctive substring "mind" to avoid quoting the apostrophe.
  await expect(
    page
      .locator(
        "textarea[name='status'], textarea[placeholder*='mind'], textarea#status_text"
      )
      .first(),
    "Expected Mastodon compose textarea after OIDC sign-in"
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
}

async function postOnMastodonViaUi(page, baseUrl, statusText) {
  await loginToMastodonViaOidc(page, baseUrl);
  const compose = page
    .locator(
      "textarea[name='status'], textarea[placeholder*='mind'], textarea#status_text"
    )
    .first();
  await compose.fill(statusText);
  // The "Publish" / "Post" / "Toot" button label changes between Mastodon
  // releases. Match the submit-role button inside the compose form.
  const publish = page.locator("button[type='submit']").filter({ hasText: /publish|post|toot/i }).first();
  await publish.click();
  // Mastodon clears the textarea after a successful post.
  await expect(compose, "Expected Mastodon compose textarea to clear after publish").toHaveValue(
    "",
    { timeout: resolveTimeout(30_000) }
  );
}

// Drive Friendica's form login (ldapauth-mediated) as biber, then post
// via the dedicated `/compose` page. The frio theme inlines a hidden
// `jot` form on /network that depends on JS state to enable the submit
// button. `/compose` renders the same form as a standalone page with
// the textarea + submit button always visible, so it is the most stable
// target for an end-to-end UI flow.
//
// Variant pattern mirrors web-app-friendica/files/playwright/playwright.spec.js:
//   v0  oauth2-proxy intercepts /login -> Keycloak round-trip, then a
//       second Friendica form because stock Friendica has no header-
//       trusted auto-login addon. The second submit triggers ldapauth
//       and starts the in-app session.
//   v2  no oauth2-proxy gating, /login is friendica's own form directly.
async function loginViaFriendicaForm(page) {
  const passwordField = page.locator("input[name='password']").first();
  await passwordField.waitFor({ state: "visible", timeout: resolveTimeout(30_000) });
  const usernameField = page.locator("input[name='username']").first();
  const loginForm = page.locator("form").filter({ has: passwordField });
  const signInButton = loginForm
    .locator("button[type='submit'], input[type='submit']")
    .or(loginForm.getByRole("button", { name: /sign\s*in|log\s*in/i }))
    .first();
  await usernameField.fill(biberUsername);
  await passwordField.fill(biberPassword);
  await Promise.all([
    page.waitForLoadState("domcontentloaded"),
    signInButton.click(),
  ]);
}

async function postOnFriendicaViaUi(page, baseUrl, statusText) {
  await page.goto(`${baseUrl}/`, { waitUntil: "domcontentloaded" }).catch(() => {});
  const friendicaHost = new URL(baseUrl).host;

  // Step 1: if oauth2-proxy intercepted, fill the Keycloak form first.
  const onKeycloak = !page.url().startsWith(baseUrl);
  if (onKeycloak) {
    await performKeycloakLoginForm(page, biberUsername, biberPassword);
    await expect
      .poll(() => {
        try { return new URL(page.url()).host; } catch { return ""; }
      }, {
        timeout: resolveTimeout(60_000),
        message: `Expected page host to return to ${friendicaHost} after Keycloak login`,
      })
      .toBe(friendicaHost);
  }

  // Step 2: Friendica's own login form. After the oauth2-proxy round-trip
  // friendica still serves its login screen because there is no header-
  // trusted SSO addon; fill it so ldapauth's else-branch starts the
  // friendica session. In v2 the password form is already visible from
  // step 1's `/` redirect to `/login`.
  await page.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) }).catch(() => {});
  if (await page.locator("input[name='password']").first().isVisible({ timeout: resolveTimeout(30_000) }).catch(() => false)) {
    await loginViaFriendicaForm(page);
  }

  await page.goto(`${baseUrl}/compose`, { waitUntil: "domcontentloaded" });
  const compose = page.locator("textarea[name='body']").first();
  await expect(
    compose,
    "Expected Friendica /compose textarea after ldapauth sign-in"
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
  await compose.fill(statusText);
  await page.locator("button[name='submit'][type='submit']").first().click();

  // Friendica redirects to /profile/<nick> after a successful post; verify
  // the post text shows up there. The /network feed only surfaces
  // contacts' posts, not your own.
  await page.goto(`${baseUrl}/profile/${biberUsername}`, { waitUntil: "domcontentloaded" });
  await expect(
    page.locator(".wall-item-body, .wall-item-content").filter({ hasText: statusText }).first(),
    "Expected Friendica profile timeline to surface the new status"
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
}

async function expectPostVisibleOnWall(page, wallUrl, needle, timeoutMs = 60000) {
  await page.goto(wallUrl);
  await expect(
    page.locator(".wall-item").filter({ hasText: needle }).first(),
    `Expected a wall-item containing "${needle}" on ${wallUrl}`
  ).toBeVisible({ timeout: timeoutMs });
}

async function expectPostAbsentFromWall(page, wallUrl, needle, settleMs = 30000) {
  await page.goto(wallUrl);
  await page.waitForTimeout(settleMs);
  await expect(
    page.locator(".wall-item").filter({ hasText: needle }),
    `Expected NO wall-item containing "${needle}" on ${wallUrl}`
  ).toHaveCount(0);
}

function urlHost(url) {
  return new URL(url).host;
}

module.exports = {
  env: {
    appBaseUrl,
    canonicalDomain,
    defaultSlug,
    wallSlugs,
    mastodonBaseUrl,
    friendicaBaseUrl,
  },
  skipUnlessServiceEnabled,
  beforeEach,
  postOnMastodonViaUi,
  postOnFriendicaViaUi,
  expectPostVisibleOnWall,
  expectPostAbsentFromWall,
  urlHost,
  runAdminFlow,
  runBiberFlow,
  runGuestFlow,
};
