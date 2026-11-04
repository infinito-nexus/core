const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const {
  normalizeBaseUrl,
  decodeDotenvQuotedValue,
  performKeycloakLoginForm,
  requireDotenvValue,
  gotoOnion,
} = require("../personas");

test.use({ ignoreHTTPSErrors: true });

const oidcIssuerUrl = normalizeBaseUrl(requireDotenvValue(process.env.OIDC_ISSUER_URL, "OIDC_ISSUER_URL"));
const discourseBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.DISCOURSE_BASE_URL, "DISCOURSE_BASE_URL"));
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);

const DIAGRAM_SOURCE = ["```mermaid", "graph TD;", "  Biber-->Dam;", "  Dam-->River;", "```"].join("\n");

async function signInViaOidc(page) {
  await gotoOnion(page, `${discourseBaseUrl}/`);
  const oidcSignIn = page
    .locator("a, button")
    .filter({ hasText: /sign\s*in\s+with\s+oidc|sign\s*in\s+with\s+sso|single\s+sign[-\s]*on|log\s*in/i })
    .first();
  if ((await oidcSignIn.count().catch(() => 0)) > 0) {
    await oidcSignIn.click();
  } else {
    await gotoOnion(page, `${discourseBaseUrl}/auth/oidc`).catch(() => {});
  }
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `expected redirect to Keycloak OIDC auth (${oidcIssuerUrl})`,
    })
    .toContain(`${oidcIssuerUrl}/protocol/openid-connect/auth`);
  await performKeycloakLoginForm(page, adminUsername, adminPassword);
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `expected redirect back to discourse at ${discourseBaseUrl}`,
    })
    .toContain(discourseBaseUrl);
}

async function publishDiagramTopic(page, title, raw) {
  return page.evaluate(
    async ({ base, topicTitle, body }) => {
      const headers = { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" };
      const csrfResponse = await fetch(`${base}/session/csrf.json`, { headers, credentials: "include" });
      if (!csrfResponse.ok) return { ok: false, stage: "csrf", status: csrfResponse.status };
      const { csrf } = await csrfResponse.json();

      const categoriesResponse = await fetch(`${base}/categories.json`, { headers, credentials: "include" });
      if (!categoriesResponse.ok) return { ok: false, stage: "categories", status: categoriesResponse.status };
      const categories = (await categoriesResponse.json()).category_list.categories;
      const writable = categories.find((category) => !category.read_only_banner) || categories[0];

      const form = new URLSearchParams({ title: topicTitle, raw: body, category: String(writable.id) });
      const postResponse = await fetch(`${base}/posts.json`, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/x-www-form-urlencoded", "X-CSRF-Token": csrf },
        credentials: "include",
        body: form.toString(),
      });
      const payload = await postResponse.json().catch(() => ({}));
      if (!postResponse.ok) return { ok: false, stage: "post", status: postResponse.status, payload };
      return { ok: true, topicSlug: payload.topic_slug, topicId: payload.topic_id };
    },
    { base: discourseBaseUrl, topicTitle: title, body: raw },
  );
}

test("discourse-mermaid: a published fence renders as a diagram", async ({ page }) => {
  skipUnlessAddonEnabled("discourse-mermaid");
  test.setTimeout(resolveTimeout(240_000));

  await page.context().clearCookies();
  await signInViaOidc(page);

  const title = `Mermaid rendering check ${Date.now()}`;
  const published = await publishDiagramTopic(page, title, DIAGRAM_SOURCE);
  expect(
    published.ok,
    `expected the topic to be created (stage ${published.stage}, status ${published.status}, ${JSON.stringify(published.payload)})`,
  ).toBe(true);

  await gotoOnion(page, `${discourseBaseUrl}/t/${published.topicSlug}/${published.topicId}`);

  const post = page.locator(".topic-post .cooked").first();
  await expect(post, "the published post must be readable").toBeVisible({ timeout: resolveTimeout(60_000) });

  await expect
    .poll(() => post.locator("svg").count(), {
      timeout: resolveTimeout(90_000),
      message: "the mermaid fence must be replaced by a rendered SVG, not shown as plain code",
    })
    .toBeGreaterThan(0);

  await expect
    .poll(() => post.locator("svg").allTextContents().then((labels) => labels.join(" ")), {
      timeout: resolveTimeout(90_000),
      message: "a rendered SVG must carry the node labels from the fence",
    })
    .toContain("Biber");
});
