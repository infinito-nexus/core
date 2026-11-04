"""The shared SSO profile lock renderer, rendered and run against a stub DOM.

The template is rendered with the selectors and languages of
``services.sso.profile`` and a catalogue, collapsed by ``to_one_liner`` as the
injector does, and executed by node behind a minimal ``document``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest

from ansible.plugins.filter.core import FilterModule as CoreFilters
from jinja2 import Environment

from plugins.filter.text_filters import to_inline_js, to_one_liner
from utils.cache.files import PROJECT_ROOT, read_text

TEMPLATES = "roles/sys-front-inj-javascript/templates"
RENDERER = f"{TEMPLATES}/profile_lock.js.j2"
CATALOGUE_TEMPLATE = f"{TEMPLATES}/profile_lock_catalogue.json.j2"
CATALOGUE_FILE = "roles/sys-front-inj-javascript/files/profile_lock_i18n.yml"
APPLICATION = "web-app-demo"
SELECTORS = {"name": "#name[data-locked]", "language": "#language[data-locked]"}
LANGUAGES = ["en", "de"]
CATALOGUE = {
    "en": {"locked": "Managed centrally.", "dir": "ltr"},
    "de": {"locked": "Zentral verwaltet.", "dir": "ltr"},
    "fr": {"locked": "Géré de manière centrale.", "dir": "ltr"},
}
HOSTILE_TEXT = ']=] /*x*/ </script> // a=b "q" \\ end'
HOSTILE_SELECTOR = '#name[data-note="]=] /*x*/ </script>"]'

HARNESS = """
const fields = {};
const observers = [];
const frames = [];
const queries = [];
function element(tagName) {
  return {
    tagName,
    readOnly: false,
    disabled: false,
    title: "",
    style: {},
    attributes: {},
    labels: [{ title: "" }],
    parentElement: { title: "" },
    setAttribute(name, value) { this.attributes[name] = String(value); },
  };
}
// Node 21+ ships a getter-only global navigator that ignores plain assignment.
Object.defineProperty(globalThis, "navigator", {
  value: { language: CONFIG.navigator },
  configurable: true,
});
globalThis.MutationObserver = class {
  constructor(callback) { observers.push(callback); }
  observe() {}
};
globalThis.requestAnimationFrame = (callback) => frames.push(callback);
globalThis.document = {
  readyState: "complete",
  documentElement: { lang: CONFIG.lang },
  addEventListener() {},
  querySelectorAll(selector) {
    queries.push(selector);
    return CONFIG.selectors.filter((known) => selector.split(",").includes(known))
      .flatMap((known) => fields[known] || []);
  },
};
for (const [selector, tags] of Object.entries(CONFIG.fields)) {
  fields[selector] = tags.map(element);
}
"""

EPILOGUE = """
for (const [selector, tags] of Object.entries(CONFIG.late)) {
  fields[selector] = (fields[selector] || []).concat(tags.map(element));
}
for (let batch = 0; batch < CONFIG.batches; batch += 1) {
  observers.forEach((callback) => callback([]));
}
const scheduled = frames.length;
frames.splice(0).forEach((callback) => callback(0));
process.stdout.write(JSON.stringify({ fields, queries, scheduled }));
"""


def _render(selectors: dict, catalogue: dict) -> str:
    """Render the renderer the way the injector serves it.

    Args:
        selectors: ``services.sso.profile.locked``.
        catalogue: what ``lookup('i18n_catalogue', ...)`` returns.
    """
    environment = Environment(autoescape=False)  # noqa: S701 - renders JavaScript, not HTML
    environment.filters.update(CoreFilters().filters())
    environment.filters["to_inline_js"] = to_inline_js
    config = {
        "services.sso.profile.locked": selectors,
        "services.sso.profile.languages": LANGUAGES,
    }

    def lookup(name: str, *terms: str):
        if name == "config" and terms[0] == APPLICATION and terms[1] in config:
            return config[terms[1]]
        if name == "i18n_catalogue" and terms == ("profile_lock", CATALOGUE_FILE):
            return catalogue
        if name == "template" and terms == (CATALOGUE_TEMPLATE,):
            return render(CATALOGUE_TEMPLATE)
        raise AssertionError(f"unexpected lookup({name!r}, {terms!r})")

    def render(path: str) -> str:
        template = environment.from_string(read_text(str(PROJECT_ROOT / path)))
        return template.render(application_id=APPLICATION, lookup=lookup)

    return to_one_liner(render(RENDERER))


def _run(
    script: str,
    lang: str,
    browser: str,
    fields: dict,
    late: dict | None = None,
    *,
    batches: int,
) -> dict:
    """Run a rendered renderer and return what the stub document saw.

    Args:
        script: the rendered, collapsed renderer.
        lang: ``document.documentElement.lang``.
        browser: ``navigator.language``.
        fields: selector mapped to the tag names of the elements it matches at load.
        late: selector mapped to the tag names of elements added after the first run.
        batches: mutation batches delivered before the next animation frame.

    Returns:
        ``fields``: selector mapped to its elements afterwards; ``queries``:
        every ``querySelectorAll`` argument in order; ``scheduled``: the
        animation frames requested by the mutation batches.
    """
    config = json.dumps(
        {
            "lang": lang,
            "navigator": browser,
            "fields": fields,
            "late": late or {},
            "selectors": sorted({*fields, *(late or {})}),
            "batches": batches,
        }
    )
    program = f"const CONFIG = {config};\n{HARNESS}\n{script}\n{EPILOGUE}"
    with tempfile.NamedTemporaryFile("w", suffix=".js") as handle:
        handle.write(program)
        handle.flush()
        proc = subprocess.run(
            ["node", handle.name], capture_output=True, text=True, check=False
        )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)


def _field(lang: str, browser: str, selector: str, tag: str) -> dict:
    """Return the one element ``selector`` matches after the renderer ran.

    Args:
        lang: ``document.documentElement.lang``.
        browser: ``navigator.language``.
        selector: the selector the element answers to.
        tag: its tag name.
    """
    script = _render(SELECTORS, CATALOGUE)
    return _run(script, lang, browser, {selector: [tag]}, batches=1)["fields"][
        selector
    ][0]


@unittest.skipUnless(shutil.which("node"), "node is not available in PATH")
class TestProfileLock(unittest.TestCase):
    def test_a_declared_input_turns_read_only_with_the_page_language_warning(self):
        field = _field("de-DE", "en-US", SELECTORS["name"], "INPUT")

        self.assertTrue(field["readOnly"])
        self.assertFalse(field["disabled"])
        self.assertEqual("Zentral verwaltet.", field["title"])
        self.assertEqual({"aria-readonly": "true"}, field["attributes"])
        self.assertEqual({"cursor": "not-allowed"}, field["style"])

    def test_the_label_and_the_wrapper_carry_the_warning_too(self):
        field = _field("de", "de", SELECTORS["name"], "INPUT")

        self.assertEqual([{"title": "Zentral verwaltet."}], field["labels"])
        self.assertEqual({"title": "Zentral verwaltet."}, field["parentElement"])

    def test_a_declared_select_is_disabled_because_it_ignores_read_only(self):
        field = _field("en", "en", SELECTORS["language"], "SELECT")

        self.assertTrue(field["disabled"])
        self.assertEqual("Managed centrally.", field["title"])

    def test_an_undeclared_selector_stays_untouched(self):
        field = _field("en", "en", "#free", "INPUT")

        self.assertFalse(field["readOnly"])
        self.assertEqual("", field["title"])

    def test_an_untranslated_page_language_falls_back_to_the_browser(self):
        field = _field("it", "de-AT", SELECTORS["name"], "INPUT")

        self.assertEqual("Zentral verwaltet.", field["title"])

    def test_an_untranslated_browser_language_falls_back_to_english(self):
        field = _field("it", "it", SELECTORS["name"], "INPUT")

        self.assertEqual("Managed centrally.", field["title"])

    def test_only_the_declared_languages_reach_the_page(self):
        script = _render(SELECTORS, CATALOGUE)
        seen = _run(script, "fr", "fr", {SELECTORS["name"]: ["INPUT"]}, batches=1)

        self.assertIn(to_inline_js(CATALOGUE["de"]["locked"])[1:-1], script)
        self.assertNotIn(to_inline_js(CATALOGUE["fr"]["locked"])[1:-1], script)
        self.assertEqual(
            "Managed centrally.", seen["fields"][SELECTORS["name"]][0]["title"]
        )

    def test_a_field_rendered_after_load_is_locked_on_the_next_frame(self):
        selector = SELECTORS["name"]
        script = _render(SELECTORS, CATALOGUE)
        seen = _run(script, "en", "en", {}, late={selector: ["INPUT"]}, batches=1)
        field = seen["fields"][selector][0]

        self.assertTrue(field["readOnly"])
        self.assertEqual("Managed centrally.", field["title"])

    def test_every_selector_is_matched_by_one_query(self):
        script = _render(SELECTORS, CATALOGUE)
        seen = _run(
            script,
            "en",
            "en",
            {SELECTORS["name"]: ["INPUT"], SELECTORS["language"]: ["SELECT"]},
            batches=0,
        )

        self.assertEqual([",".join(SELECTORS.values())], seen["queries"])
        self.assertTrue(seen["fields"][SELECTORS["name"]][0]["readOnly"])
        self.assertTrue(seen["fields"][SELECTORS["language"]][0]["disabled"])

    def test_mutation_batches_before_a_frame_cost_one_query(self):
        selector = SELECTORS["name"]
        script = _render(SELECTORS, CATALOGUE)
        seen = _run(script, "en", "en", {}, late={selector: ["INPUT"]}, batches=3)

        self.assertEqual(1, seen["scheduled"])
        self.assertEqual(2, len(seen["queries"]))
        self.assertTrue(seen["fields"][selector][0]["readOnly"])

    def test_a_hostile_catalogue_and_selector_survive_the_inline_script(self):
        catalogue = {"en": {"locked": HOSTILE_TEXT, "dir": "ltr"}}
        script = _render({"name": HOSTILE_SELECTOR}, catalogue)
        seen = _run(script, "en", "en", {HOSTILE_SELECTOR: ["INPUT"]}, batches=1)

        for sequence in ("]=]", "</script", "/*"):
            self.assertNotIn(sequence, script)
        self.assertEqual(HOSTILE_TEXT, seen["fields"][HOSTILE_SELECTOR][0]["title"])

    def test_a_run_of_spaces_in_the_warning_survives_the_one_liner(self):
        catalogue = {"en": {"locked": "Managed  centrally.", "dir": "ltr"}}
        script = _render(SELECTORS, catalogue)
        seen = _run(script, "en", "en", {SELECTORS["name"]: ["INPUT"]}, batches=1)

        self.assertEqual(
            "Managed  centrally.", seen["fields"][SELECTORS["name"]][0]["title"]
        )


if __name__ == "__main__":
    unittest.main()
