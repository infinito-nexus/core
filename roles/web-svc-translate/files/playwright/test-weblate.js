const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const SOURCE = "The reviewed sentence wins over every engine.";
const REVIEWED = "Der geprüfte Satz gewinnt gegen jede Maschine.";
const COMPONENT = "gateway-memory";
const LANGUAGE = "de";
const SOURCE_LANGUAGE = "en";
const APPROVED = 30;
const BASE_CATALOGUE = `msgid ""\nmsgstr ""\n\nmsgid "${COMPONENT}"\nmsgstr "${SOURCE}"\n`;

async function ensureProject(shared, request) {
  const existing = await shared.weblate(request, `projects/${shared.weblateProject}/`);
  if (existing.response.ok()) {
    return;
  }
  const created = await shared.weblate(request, "projects/", {
    method: "POST",
    data: {
      name: shared.weblateProject,
      slug: shared.weblateProject,
      web: shared.weblateProjectHomepage,
      translation_review: true,
    },
  });
  expect(created.response.status(), `Weblate refused the project: ${await created.response.text()}`).toBe(201);
}

async function ensureComponent(shared, request) {
  const existing = await shared.weblate(request, `components/${shared.weblateProject}/${COMPONENT}/`);
  if (existing.response.ok()) {
    return;
  }
  const created = await shared.weblate(request, `projects/${shared.weblateProject}/components/`, {
    method: "POST",
    multipart: {
      name: COMPONENT,
      slug: COMPONENT,
      file_format: "po-mono",
      source_language: SOURCE_LANGUAGE,
      docfile: {
        name: `${SOURCE_LANGUAGE}.po`,
        mimeType: "text/x-gettext-translation",
        buffer: Buffer.from(BASE_CATALOGUE),
      },
    },
  });
  expect(created.response.status(), `Weblate refused the component: ${await created.response.text()}`).toBe(201);
}

async function ensureTranslation(shared, request) {
  const existing = await shared.weblate(request, `translations/${shared.weblateProject}/${COMPONENT}/${LANGUAGE}/`);
  if (existing.response.ok()) {
    return;
  }
  const created = await shared.weblate(request, `components/${shared.weblateProject}/${COMPONENT}/translations/`, {
    method: "POST",
    data: { language_code: LANGUAGE },
  });
  expect(created.response.status(), `Weblate refused the translation: ${await created.response.text()}`).toBe(201);
}

async function unitOf(shared, request) {
  const found = await shared.weblate(
    request,
    `translations/${shared.weblateProject}/${COMPONENT}/${LANGUAGE}/units/?q=${encodeURIComponent(`source:="${SOURCE}"`)}`,
  );
  expect(found.response.ok(), `Weblate refused the unit search: ${await found.response.text()}`).toBe(true);
  return (found.body.results || [])[0];
}

async function ensureReviewedUnit(shared, request) {
  let unit;
  await expect
    .poll(async () => Boolean((unit = await unitOf(shared, request))), {
      message: `Expected ${SOURCE_LANGUAGE} to reach ${LANGUAGE}; Weblate propagates a new base string asynchronously`,
      timeout: resolveTimeout(180_000),
      intervals: [2_000],
    })
    .toBe(true);
  const reviewed = await shared.weblate(request, `units/${unit.id}/`, {
    method: "PATCH",
    data: { target: [REVIEWED], state: APPROVED },
  });
  expect(reviewed.response.ok(), `Weblate refused the review: ${await reviewed.response.text()}`).toBe(true);
  expect(reviewed.body.state, "Expected the unit to be approved").toBe(APPROVED);
}

exports.register = function (shared) {
  test.describe("the translation memory outranks every engine", () => {
    test.skip(!shared.weblateEnabled, "web-app-weblate is not deployed in this round");

    test("a reviewed string is returned verbatim and no engine answers", async ({ request }) => {
      await ensureProject(shared, request);
      await ensureComponent(shared, request);
      await ensureTranslation(shared, request);
      await ensureReviewedUnit(shared, request);

      const body = await shared.translate(request, { q: SOURCE, source: "en", target: LANGUAGE });

      expect(body.translatedText, "Expected the reviewed translation verbatim").toBe(REVIEWED);
      expect(body.engine, "Expected the memory to answer, not an engine").toBe("weblate");
    });
  });
};
