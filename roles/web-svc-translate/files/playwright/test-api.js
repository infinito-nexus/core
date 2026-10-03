const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

exports.register = function (shared) {
  test("translate answers a known string in the LibreTranslate shape", async ({ request }) => {
    const body = await shared.translate(request, { q: "House", source: "en", target: "de", format: "text" });

    expect(typeof body.translatedText, "Expected a translatedText string").toBe("string");
    expect(body.translatedText.trim().length, "Expected a non-empty translation").toBeGreaterThan(0);
    expect(shared.engines, `Expected the answering engine to be one of ${shared.engines}`).toContain(body.engine);
  });

  test("a repeated request is answered from the cache by the same engine", async ({ request }) => {
    const first = await shared.translate(request, { q: "The cached sentence stays the same.", source: "en", target: "de" });
    const second = await shared.translate(request, { q: "The cached sentence stays the same.", source: "en", target: "de" });

    expect(second.engine, "Expected the cached answer to come from the engine that produced it").toBe(first.engine);
    expect(second.translatedText, "Expected the cached translation verbatim").toBe(first.translatedText);
  });

  test("a request without a target language is refused", async ({ request }) => {
    const response = await shared.post(request, "/translate", { q: "House", source: "en" });

    expect(response.status(), "Expected the gateway to refuse a request it cannot route").toBe(422);
    expect((await response.json()).error, "Expected an error, never the source text").toBeTruthy();
  });

  test("languages answers a catalogue", async ({ request }) => {
    const response = await request.get(shared.url("/languages"), {
      failOnStatusCode: false,
      timeout: resolveTimeout(120_000),
    });

    expect(response.status()).toBe(200);
    expect(Array.isArray(await response.json()), "Expected a list of language codes").toBe(true);
  });

  test("detect answers a language candidate", async ({ request }) => {
    const response = await shared.post(request, "/detect", { q: "Dies ist ein deutscher Satz." });

    expect([200, 503], "Expected a candidate or a loud refusal").toContain(response.status());
    if (response.status() === 200) {
      const candidates = await response.json();
      expect(Array.isArray(candidates)).toBe(true);
      expect(candidates[0].language, "Expected a language code").toBeTruthy();
    }
  });
};
