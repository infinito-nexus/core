const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("lang=de and Accept-Language: de return the German description", async ({ request }) => {
    const english = (await shared.getJson(request, `/v1/roles/${shared.translatedRole}`, { ref: "deployed" })).body;
    expect(english.language).toBe("en");

    const byParameter = await shared.getJson(request, `/v1/roles/${shared.translatedRole}`, { ref: "deployed", lang: "de" });
    expect(byParameter.body.language).toBe("de");
    expect(byParameter.response.headers()["content-language"]).toBe("de");
    expect(byParameter.body.role.description).not.toBe(english.role.description);

    const byHeader = await shared.getJson(
      request,
      `/v1/roles/${shared.translatedRole}`,
      { ref: "deployed" },
      { "Accept-Language": "de-DE,de;q=0.9,en;q=0.5" },
    );
    expect(byHeader.body.language).toBe("de");
    expect(byHeader.body.role.description).toBe(byParameter.body.role.description);

    const catalog = (await shared.getJson(request, "/v1/catalogs/core/de", { ref: "deployed" })).body;
    const context = `role:${shared.translatedRole}:description`;
    expect(catalog.messages[context][english.role.description]).toBe(byParameter.body.role.description);
  });

  test("languages list all 184 ISO languages with their translated share", async ({ request }) => {
    const { body } = await shared.getJson(request, "/v1/languages", { ref: "deployed" });
    expect(body.languages).toHaveLength(184);
    const byCode = Object.fromEntries(body.languages.map((language) => [language.code, language]));
    expect(byCode.de.native).toBe("Deutsch");
    expect(byCode.de.translated).toBeGreaterThan(0.9);
    expect(byCode.ar.direction).toBe("rtl");
    expect(byCode.en.translated).toBe(1);
  });

  test("unknown languages answer 404", async ({ request }) => {
    expect(await shared.statusOf(request, "/v1/roles", { ref: "deployed", lang: "xx" })).toBe(404);
    expect(await shared.statusOf(request, "/v1/catalogs/core/xx", { ref: "deployed" })).toBe(404);
  });
};
