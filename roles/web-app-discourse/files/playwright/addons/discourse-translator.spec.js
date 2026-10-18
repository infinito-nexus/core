const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { normalizeBaseUrl, decodeDotenvQuotedValue, requireDotenvValue } = require("../personas");
const { signInAsAdmin } = require("../sign-in");

test.use({ ignoreHTTPSErrors: true });

const discourseBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.DISCOURSE_BASE_URL, "DISCOURSE_BASE_URL"));
const expectedEndpoint = decodeDotenvQuotedValue(process.env.DISCOURSE_TRANSLATE_ENDPOINT);
const expectedProvider = decodeDotenvQuotedValue(process.env.DISCOURSE_TRANSLATE_PROVIDER);

const GERMAN_TITLE = "Ein deutscher Beitrag für den Übersetzungsdienst";
const GERMAN_BODY =
  "Dieser Beitrag ist auf Deutsch verfasst, damit der Übersetzungsdienst ihn ins Englische übersetzen muss.";

function settingValue(settings, name) {
  const found = settings.find((entry) => entry && entry.setting === name);
  expect(found, `${name} site setting must exist (the discourse-translator plugin must be loaded)`).toBeTruthy();
  return String(found.value);
}

function readCsrf(page, origin) {
  return page.evaluate(async (base) => {
    const res = await fetch(`${base}/session/csrf.json`, {
      headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
      credentials: "include",
    });
    const body = res.ok ? await res.json() : {};
    return (
      (body && body.csrf) ||
      document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") ||
      ""
    );
  }, origin);
}

function callJson(page, { origin, path, method, payload = null, csrf = "" }) {
  return page.evaluate(
    async ({ base, route, verb, body, token }) => {
      const headers = { Accept: "application/json" };
      const init = { method: verb, credentials: "include", headers };
      if (verb !== "GET") {
        headers["Content-Type"] = "application/json";
        headers["X-Requested-With"] = "XMLHttpRequest";
        headers["X-CSRF-Token"] = token;
        init.body = JSON.stringify(body);
      }
      const res = await fetch(`${base}${route}`, init);
      const text = await res.text();
      let parsed;
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = { raw: text.slice(0, 500) };
      }
      return { status: res.status, body: parsed };
    },
    { base: origin, route: path, verb: method, body: payload, token: csrf },
  );
}

test("discourse-translator: posts are translated through the in-cluster gateway", async ({ page }) => {
  skipUnlessAddonEnabled("discourse-translator");
  skipUnlessServiceEnabled("translate");
  test.setTimeout(resolveTimeout(240_000));

  expect(expectedEndpoint, "DISCOURSE_TRANSLATE_ENDPOINT must be set").toBeTruthy();
  expect(expectedProvider, "DISCOURSE_TRANSLATE_PROVIDER must be set").toBeTruthy();

  const endpointUrl = new URL(expectedEndpoint);
  expect(
    endpointUrl.protocol,
    "the gateway must be reached as plain http on the container network; https would mean the translation leaves through the public ingress",
  ).toBe("http:");
  expect(
    endpointUrl.hostname.includes("."),
    `the gateway host must be an undotted container name (got "${endpointUrl.hostname}"); a dotted host routes the translation through the public front proxy`,
  ).toBe(false);
  expect(
    endpointUrl.host.toLowerCase(),
    "the gateway must be a distinct in-cluster service, not Discourse itself",
  ).not.toBe(new URL(discourseBaseUrl).host.toLowerCase());

  await page.context().clearCookies();
  await signInAsAdmin(page);

  const settings = await callJson(page, {
    origin: discourseBaseUrl,
    path: "/admin/site_settings.json",
    method: "GET",
  });
  expect(settings.status, `expected /admin/site_settings.json to answer as admin (status ${settings.status})`).toBe(200);

  const entries = (settings.body && settings.body.site_settings) || [];
  expect(settingValue(entries, "translator_enabled"), "the translator must be switched on").toBe("true");
  expect(settingValue(entries, "translator_provider"), "the provider must be the gateway's dialect").toBe(expectedProvider);
  expect(
    settingValue(entries, "translator_libretranslate_endpoint"),
    "the translator must post to the deployed gateway",
  ).toBe(expectedEndpoint);

  const csrf = await readCsrf(page, discourseBaseUrl);
  expect(csrf, "expected /session/csrf.json to hand the signed-in admin a token").toBeTruthy();

  const catalogue = await callJson(page, {
    origin: discourseBaseUrl,
    path: "/categories.json",
    method: "GET",
  });
  expect(catalogue.status, `expected /categories.json to answer as admin (status ${catalogue.status})`).toBe(200);
  const categories = (catalogue.body && catalogue.body.category_list && catalogue.body.category_list.categories) || [];
  const category = categories.find((entry) => !entry.read_only_banner) || categories[0];
  expect(
    category,
    "the source topic needs a category: Discourse refuses an uncategorized topic unless allow_uncategorized_topics is on",
  ).toBeTruthy();

  const nonce = Date.now().toString(36);
  const created = await callJson(page, {
    origin: discourseBaseUrl,
    path: "/posts.json",
    method: "POST",
    csrf,
    payload: {
      title: `${GERMAN_TITLE} ${nonce}`,
      raw: `${GERMAN_BODY} Kennung ${nonce}.`,
      category: category.id,
      archetype: "regular",
    },
  });
  expect(
    created.status,
    `the admin must be able to post the German source topic (status ${created.status}): ${JSON.stringify(created.body.errors || created.body.raw || "")}`,
  ).toBe(200);

  const postId = created.body && created.body.id;
  expect(postId, "the created post must carry an id the translator can be pointed at").toBeTruthy();
  const sourceHtml = String((created.body && created.body.cooked) || "");
  expect(sourceHtml.trim().length, "the created post must carry its cooked German source").toBeGreaterThan(0);

  const translated = await callJson(page, {
    origin: discourseBaseUrl,
    path: "/translator/translate",
    method: "POST",
    csrf,
    payload: { post_id: postId },
  });
  expect(
    translated.status,
    `Discourse must translate the post server-side through ${expectedEndpoint} (status ${translated.status}): ${JSON.stringify(translated.body.errors || translated.body.raw || translated.body)}`,
  ).toBe(200);

  expect(
    String((translated.body && translated.body.detected_lang) || ""),
    "the gateway must answer the language detection the translator asks for first",
  ).toBeTruthy();

  const translation = String((translated.body && translated.body.translation) || "");
  expect(translation.trim().length, "the gateway must answer with a translation, never an empty body").toBeGreaterThan(0);
  expect(
    translation,
    "the answer must be a translation, not the German source handed back: an echoed source is stored as a translation and outlives the fix",
  ).not.toBe(sourceHtml);
});
