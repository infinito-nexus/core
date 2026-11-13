"""The shared lock renderer, rendered and run against a stub DOM.

The template is rendered with the entries ``lookup('field_locks', ...)`` builds
from the ``enforced`` fields of a ``meta/forms.yml``, its ``sso.<claim>``
fields included, and a catalogue, collapsed by ``to_one_liner`` as the
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
from utils.roles.applications import forms

TEMPLATES = "roles/sys-front-inj-javascript/templates"
RENDERER = f"{TEMPLATES}/profile_lock.js.j2"
CATALOGUE_TEMPLATE = f"{TEMPLATES}/profile_lock_catalogue.json.j2"
CATALOGUE_FILE = "roles/sys-front-inj-javascript/files/profile_lock_i18n.yml"
APPLICATION = "web-app-demo"
SELECTORS = {"name": "#name[data-locked]", "language": "#language[data-locked]"}
LANGUAGES = ["en", "de"]
CATALOGUE = {
    "en": {
        "locked": "Managed centrally.",
        "managed": "Managed by the deployment at",
        "banner": "Managed here:",
        "unlock": "Edit anyway?",
        "dir": "ltr",
    },
    "de": {
        "locked": "Zentral verwaltet.",
        "managed": "Vom Deployment verwaltet unter",
        "banner": "Hier verwaltet:",
        "unlock": "Trotzdem bearbeiten?",
        "dir": "ltr",
    },
    "fr": {"locked": "Géré de manière centrale.", "dir": "ltr"},
}
HOSTILE_TEXT = ']=] /*x*/ </script> // a=b "q" \\ end'
HOSTILE_SELECTOR = '#name[data-note="]=] /*x*/ </script>"]'
PAGE = "/admin/settings"
FORMS = {
    "general": {
        "path": PAGE,
        "fields": {
            "title": {
                "source": "design.label",
                "mode": "enforced",
                "selector": "#title",
                "label": "Site title",
                "type": "text",
            },
            "smtp_password": {
                "source": "secrets.credentials.smtp_password",
                "mode": "enforced",
                "selector": "#smtp_password",
                "type": "password",
            },
            "admin_email": {
                "source": "users.administrator.email",
                "mode": "seeded",
                "selector": "#admin_email",
                "type": "email",
            },
        },
    },
    "mail": {
        "path": "/admin/mail",
        "fields": {
            "sender": {
                "source": "mail.sender",
                "mode": "enforced",
                "selector": "#sender",
                "type": "email",
            },
        },
    },
}
TITLE_PATH = f"applications.{APPLICATION}.design.label"
SECRET_PATH = f"applications.{APPLICATION}.secrets.credentials.smtp_password"

HARNESS = """
const fields = {};
const observers = [];
const frames = [];
const queries = [];
const listeners = new Map();
const confirms = [];
const created = [];
function listenable(target) {
  target.addEventListener = function (type, callback) {
    const known = listeners.get(this) || [];
    known.push({ type, callback });
    listeners.set(this, known);
  };
  return target;
}
function element(spec) {
  const shape = typeof spec === "string" ? { tagName: spec } : spec;
  return listenable({
    tagName: shape.tagName,
    type: shape.type || "text",
    name: shape.name || "",
    value: shape.value || "",
    checked: Boolean(shape.checked),
    selectedOptions: (shape.selected || []).map((value) => ({ value })),
    readOnly: Boolean(shape.readOnly),
    disabled: Boolean(shape.disabled),
    title: "",
    style: {},
    attributes: {},
    labels: [listenable({ title: "" })],
    parentElement: { title: "" },
    form: CONFIG.form ? { name: "settings", parentNode: body } : null,
    setAttribute(name, value) { this.attributes[name] = String(value); },
    removeAttribute(name) { delete this.attributes[name]; },
    insertAdjacentElement(position, node) {
      this.carriers = (this.carriers || []).concat([{ position, node }]);
    },
  });
}
const body = {
  children: [],
  firstChild: null,
  insertBefore(child, anchor) {
    child.parentName = anchor && anchor.name ? anchor.name : "body";
    this.children.push(child);
  },
};
// Node 21+ ships a getter-only global navigator that ignores plain assignment.
Object.defineProperty(globalThis, "navigator", {
  value: { language: CONFIG.navigator },
  configurable: true,
});
globalThis.window = globalThis;
const routes = [];
globalThis.addEventListener = (type, callback) => { routes.push({ type, callback }); };
globalThis.location = { pathname: CONFIG.pathname, search: CONFIG.search, hash: CONFIG.hash };
globalThis.confirm = (text) => { confirms.push(text); return CONFIG.confirm; };
globalThis.MutationObserver = class {
  constructor(callback) { observers.push(callback); }
  observe() {}
};
globalThis.requestAnimationFrame = (callback) => frames.push(callback);
globalThis.document = {
  readyState: "complete",
  documentElement: { lang: CONFIG.lang },
  body,
  addEventListener() {},
  getElementById(id) { return body.children.find((child) => child.id === id) || null; },
  createElement(tagName) {
    const child = {
      tagName,
      id: "",
      textContent: "",
      style: {},
      attributes: {},
      setAttribute(name, value) { this.attributes[name] = String(value); },
      remove() {
        const at = body.children.indexOf(this);
        if (at >= 0) { body.children.splice(at, 1); }
        this.removed = true;
      },
    };
    created.push(tagName);
    return child;
  },
  querySelectorAll(selector) {
    queries.push(selector);
    return CONFIG.selectors.filter((known) => selector.split(",").includes(known))
      .flatMap((known) => fields[known] || []);
  },
  querySelector(selector) { return (fields[selector] || [])[0] || null; },
};
for (const [selector, tags] of Object.entries(CONFIG.fields)) {
  fields[selector] = tags.map(element);
}
"""

EPILOGUE = """
function add(late) {
  for (const [selector, tags] of Object.entries(late)) {
    fields[selector] = (fields[selector] || []).concat(tags.map(element));
  }
}
function assign(values) {
  for (const [selector, value] of Object.entries(values)) {
    (fields[selector] || []).forEach((field) => { field.value = value; });
  }
}
function settle() {
  observers.forEach((callback) => callback([]));
  frames.splice(0).forEach((callback) => callback(0));
}
add(CONFIG.late);
assign(CONFIG.valuesAfter);
if (CONFIG.hashAfter !== null) {
  location.hash = CONFIG.hashAfter;
  routes.filter(({ type }) => type === "hashchange").forEach(({ callback }) => callback());
}
for (let batch = 0; batch < CONFIG.batches; batch += 1) {
  observers.forEach((callback) => callback([]));
}
const scheduled = frames.length;
frames.splice(0).forEach((callback) => callback(0));
if (CONFIG.dblclick.length) {
  for (const selector of CONFIG.dblclick) {
    for (const field of fields[selector] || []) {
      const target = CONFIG.onLabel ? field.labels[0] : field;
      if (target.disabled) { continue; }
      for (const { type, callback } of listeners.get(target) || []) {
        if (type === "dblclick") { callback(); }
      }
    }
  }
  settle();
}
for (const stage of CONFIG.then) {
  add(stage.late || {});
  assign(stage.values || {});
  settle();
}
const banners = body.children.map((child) => ({
  id: child.id,
  role: child.attributes.role,
  text: child.textContent,
  parent: child.parentName,
}));
process.stdout.write(JSON.stringify({ fields, queries, scheduled, confirms, created, banners }));
"""


def _render(
    selectors: dict,
    catalogue: dict,
    managed: dict | None = None,
    languages: list[str] | None = LANGUAGES,
    application: dict | None = None,
) -> str:
    """Render the renderer the way the injector serves it.

    Args:
        selectors: the selector of each ``sso.<claim>`` field of a profile
            form on every page; empty for a role without.
        catalogue: what ``lookup('i18n_catalogue', ...)`` returns.
        managed: the other forms of the role's ``meta/forms.yml``, if it
            ships one.
        languages: ``services.sso.profile.languages``; ``None`` for a role
            that declares none.
        application: the rendered ``applications.<role>`` the forms resolve against.
    """
    environment = Environment(autoescape=False)  # noqa: S701 - renders JavaScript, not HTML
    environment.filters.update(CoreFilters().filters())
    environment.filters["to_inline_js"] = to_inline_js
    profile = {
        field: {"source": f"sso.{field}", "mode": "enforced", "selector": selector}
        for field, selector in selectors.items()
    }
    declared = {"profile": {"path": "/", "fields": profile}} if profile else {}
    field_locks = {
        "locks": forms.locks(
            APPLICATION, declared | (managed or {}), application or {}, {}, {}
        ),
        "languages": languages,
    }

    def lookup(name: str, *terms: str):
        if name == "field_locks" and terms == (APPLICATION,):
            return field_locks
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
    page: str = PAGE,
    dblclick: tuple[str, ...] = (),
    on_label: bool = False,
    confirm: bool = True,
    form: bool = False,
    hash_after: str | None = None,
    values_after: dict | None = None,
    then: tuple[dict, ...] = (),
) -> dict:
    """Run a rendered renderer and return what the stub document saw.

    Args:
        script: the rendered, collapsed renderer.
        lang: ``document.documentElement.lang``.
        browser: ``navigator.language``.
        fields: selector mapped to the tag names, or element specs, of the
            elements it matches at load.
        late: selector mapped to the tag names of elements added after the first run.
        batches: mutation batches delivered before the next animation frame.
        page: ``location.pathname`` plus ``location.search`` and ``location.hash``.
        dblclick: selectors whose fields get a double-click after the first
            frame, except a disabled target, which a browser leaves without
            one; one more mutation batch and frame follow.
        on_label: double-click the first label of each field instead.
        confirm: what the confirmation dialog answers.
        form: whether every field sits in a form.
        hash_after: the ``location.hash`` a ``hashchange`` sets after the first run.
        values_after: selector mapped to the value its elements hold after the first run.
        then: stages after the double-click, each a mapping of ``late``
            (selector mapped to the tag names or element specs it adds) and
            ``values`` (selector mapped to the value its elements hold), each
            followed by one mutation batch and frame.

    Returns:
        ``fields``: selector mapped to its elements afterwards; ``queries``:
        every ``querySelectorAll`` argument in order; ``scheduled``: the
        animation frames requested by the mutation batches; ``confirms``: the
        text of every confirmation dialog; ``created``: the tag of every
        created element; ``banners``: the banners in the body.
    """
    location, _, route = page.partition("#")
    pathname, _, search = location.partition("?")
    config = json.dumps(
        {
            "lang": lang,
            "navigator": browser,
            "fields": fields,
            "late": late or {},
            "selectors": sorted(
                {
                    *fields,
                    *(late or {}),
                    *(key for stage in then for key in stage.get("late", {})),
                }
            ),
            "batches": batches,
            "pathname": pathname,
            "search": f"?{search}" if search else "",
            "hash": f"#{route}" if route else "",
            "hashAfter": hash_after,
            "valuesAfter": values_after or {},
            "dblclick": list(dblclick),
            "onLabel": on_label,
            "confirm": confirm,
            "form": form,
            "then": list(then),
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


def _managed(**kwargs) -> dict:
    """Run the renderer of a role with the profile lock and ``FORMS``.

    Args:
        kwargs: passed to ``_run``; ``fields`` defaults to one input per
            declared selector.
    """
    fields = kwargs.pop(
        "fields",
        {
            SELECTORS["name"]: ["INPUT"],
            "#title": ["INPUT"],
            "#smtp_password": ["INPUT"],
            "#admin_email": ["INPUT"],
            "#sender": ["INPUT"],
        },
    )
    script = _render(SELECTORS, CATALOGUE, FORMS)
    return _run(script, "en", "en", fields, batches=1, **kwargs)


@unittest.skipUnless(shutil.which("node"), "node is not available in PATH")
class TestManagedFieldLock(unittest.TestCase):
    def test_an_enforced_field_names_the_deployment_and_its_inventory_path(self):
        title = _managed()["fields"]["#title"][0]

        self.assertTrue(title["readOnly"])
        self.assertEqual(f"Managed by the deployment at {TITLE_PATH}", title["title"])
        self.assertEqual([{"title": title["title"]}], title["labels"])

    def test_the_sentence_follows_the_page_language(self):
        script = _render(SELECTORS, CATALOGUE, FORMS)
        seen = _run(script, "de", "en", {"#title": ["INPUT"]}, batches=1)

        self.assertEqual(
            f"Vom Deployment verwaltet unter {TITLE_PATH}",
            seen["fields"]["#title"][0]["title"],
        )

    def test_a_role_without_profile_languages_carries_every_language(self):
        script = _render({}, CATALOGUE, FORMS, languages=None)
        seen = _run(script, "fr", "fr", {"#title": ["INPUT"]}, batches=1)

        self.assertIn(to_inline_js(CATALOGUE["fr"]["locked"])[1:-1], script)
        self.assertTrue(seen["fields"]["#title"][0]["readOnly"])

    def test_the_profile_field_keeps_the_profile_warning(self):
        name = _managed()["fields"][SELECTORS["name"]][0]

        self.assertEqual("Managed centrally.", name["title"])

    def test_a_seeded_field_carries_no_marker(self):
        email = _managed()["fields"]["#admin_email"][0]

        self.assertFalse(email["readOnly"])
        self.assertEqual("", email["title"])
        self.assertEqual({}, email["attributes"])

    def test_a_field_of_another_page_is_neither_locked_nor_listed(self):
        seen = _managed()

        self.assertFalse(seen["fields"]["#sender"][0]["readOnly"])
        self.assertNotIn("#sender", seen["queries"])
        self.assertNotIn("mail.sender", seen["banners"][0]["text"])

    def test_a_page_query_string_still_matches_its_form(self):
        seen = _managed(page=f"{PAGE}?updated=true")

        self.assertTrue(seen["fields"]["#title"][0]["readOnly"])

    def test_the_page_shows_one_banner_listing_its_managed_fields(self):
        seen = _managed(form=True, late={"#title": ["INPUT"]})

        self.assertEqual(
            [
                {
                    "id": "infinito-managed-fields",
                    "role": "note",
                    "text": (
                        f"Managed here: Site title: {TITLE_PATH}; "
                        f"smtp_password: {SECRET_PATH}"
                    ),
                    "parent": "settings",
                }
            ],
            seen["banners"],
        )
        self.assertEqual(["div"], seen["created"])

    def test_a_page_without_a_managed_field_shows_no_banner(self):
        seen = _managed(fields={SELECTORS["name"]: ["INPUT"], "#title": []})

        self.assertEqual([], seen["banners"])
        self.assertEqual([], seen["created"])

    def test_a_double_click_unlocks_the_field_after_the_confirmation(self):
        seen = _managed(dblclick=("#title",))
        title = seen["fields"]["#title"][0]

        self.assertEqual(["Edit anyway?"], seen["confirms"])
        self.assertFalse(title["readOnly"])
        self.assertEqual("", title["title"])
        self.assertEqual({}, title["attributes"])
        self.assertEqual("", title["style"]["cursor"])

    def test_a_double_click_on_the_label_unlocks_a_disabled_select(self):
        seen = _managed(
            fields={"#title": ["SELECT"]}, dblclick=("#title",), on_label=True
        )
        title = seen["fields"]["#title"][0]

        self.assertEqual(["Edit anyway?"], seen["confirms"])
        self.assertFalse(title["disabled"])

    def test_a_declined_confirmation_keeps_the_field_locked(self):
        seen = _managed(dblclick=("#title",), confirm=False)
        title = seen["fields"]["#title"][0]

        self.assertEqual(["Edit anyway?"], seen["confirms"])
        self.assertTrue(title["readOnly"])
        self.assertEqual(f"Managed by the deployment at {TITLE_PATH}", title["title"])

    def test_a_profile_field_offers_no_unlock(self):
        seen = _managed(dblclick=(SELECTORS["name"],))

        self.assertEqual([], seen["confirms"])
        self.assertTrue(seen["fields"][SELECTORS["name"]][0]["readOnly"])

    def test_a_secret_input_is_locked_with_its_value_hidden(self):
        seen = _managed()
        secret = seen["fields"]["#smtp_password"][0]
        title = seen["fields"]["#title"][0]

        self.assertTrue(secret["readOnly"])
        self.assertEqual("password", secret["type"])
        self.assertEqual("text", title["type"])


CONSOLE = "/admin/console/"
ROUTE = f"{CONSOLE}#/demo/clients/"
CLIENT_HASH = "#/demo/clients/9f2c/settings"
REALM_HASH = "#/demo/realm-settings"
ROUTED_FORMS = {
    "client": {
        "path": ROUTE,
        "fields": {
            "redirects": {
                "source": "design.label",
                "mode": "enforced",
                "selector": "#redirects",
                "label": "Redirect URIs",
                "type": "text",
            },
        },
    },
}


CREATED = ["web-app-demo", "web-app-demo-saml"]
RECORD_FORMS = {
    "client": {
        **ROUTED_FORMS["client"],
        "record": {"selector": "#clientId", "source": "clients.created"},
    },
}


def _routed(**kwargs) -> dict:
    """Run the renderer of a role whose form lives on a ``#/`` route.

    Args:
        kwargs: passed to ``_run``; ``fields`` defaults to the redirects
            input, ``forms`` to ``ROUTED_FORMS`` and ``batches`` to one.
    """
    fields = kwargs.pop("fields", {"#redirects": ["INPUT"]})
    script = _render(
        {},
        CATALOGUE,
        kwargs.pop("forms", ROUTED_FORMS),
        application={"clients": {"created": CREATED}},
    )
    batches = kwargs.pop("batches", 1)
    return _run(script, "en", "en", fields, batches=batches, **kwargs)


def _client(client_id: str) -> dict:
    return {
        "#clientId": [{"tagName": "INPUT", "value": client_id}],
        "#redirects": ["INPUT"],
    }


@unittest.skipUnless(shutil.which("node"), "node is not available in PATH")
class TestRoutedPage(unittest.TestCase):
    def test_a_hash_route_matches_the_location_hash(self):
        seen = _routed(page=CONSOLE + CLIENT_HASH)

        self.assertTrue(seen["fields"]["#redirects"][0]["readOnly"])
        self.assertEqual(1, len(seen["banners"]))

    def test_another_hash_route_leaves_the_field_alone(self):
        seen = _routed(page=CONSOLE + REALM_HASH)

        self.assertFalse(seen["fields"]["#redirects"][0]["readOnly"])
        self.assertEqual([], seen["banners"])

    def test_a_page_without_a_route_ignores_the_location_hash(self):
        seen = _managed(page=f"{PAGE}#/anything")

        self.assertTrue(seen["fields"]["#title"][0]["readOnly"])

    def test_a_hash_change_locks_on_the_next_frame(self):
        seen = _routed(page=CONSOLE + REALM_HASH, hash_after=CLIENT_HASH, batches=0)

        self.assertEqual(1, seen["scheduled"])
        self.assertTrue(seen["fields"]["#redirects"][0]["readOnly"])

    def test_leaving_the_route_releases_the_field(self):
        seen = _routed(page=CONSOLE + CLIENT_HASH, hash_after=REALM_HASH, batches=0)
        field = seen["fields"]["#redirects"][0]

        self.assertFalse(field["readOnly"])
        self.assertEqual("", field["title"])
        self.assertEqual([{"title": ""}], field["labels"])
        self.assertEqual({"title": ""}, field["parentElement"])
        self.assertEqual({}, field["attributes"])
        self.assertEqual("", field["style"]["cursor"])
        self.assertEqual([], seen["banners"])


@unittest.skipUnless(shutil.which("node"), "node is not available in PATH")
class TestRecordGuard(unittest.TestCase):
    def test_a_record_the_deployment_created_is_locked(self):
        seen = _routed(
            forms=RECORD_FORMS, fields=_client(CREATED[1]), page=CONSOLE + CLIENT_HASH
        )

        self.assertTrue(seen["fields"]["#redirects"][0]["readOnly"])
        self.assertEqual(1, len(seen["banners"]))

    def test_a_record_an_admin_created_stays_editable(self):
        seen = _routed(
            forms=RECORD_FORMS, fields=_client("admin-made"), page=CONSOLE + CLIENT_HASH
        )
        field = seen["fields"]["#redirects"][0]

        self.assertFalse(field["readOnly"])
        self.assertEqual("", field["title"])
        self.assertEqual([], seen["banners"])

    def test_a_page_without_the_record_input_locks_nothing(self):
        seen = _routed(
            forms=RECORD_FORMS,
            fields={"#redirects": ["INPUT"]},
            page=CONSOLE + CLIENT_HASH,
        )

        self.assertFalse(seen["fields"]["#redirects"][0]["readOnly"])

    def test_turning_to_an_admin_record_releases_the_field(self):
        seen = _routed(
            forms=RECORD_FORMS,
            fields=_client(CREATED[0]),
            page=CONSOLE + CLIENT_HASH,
            values_after={"#clientId": "admin-made"},
        )
        field = seen["fields"]["#redirects"][0]

        self.assertFalse(field["readOnly"])
        self.assertEqual("", field["title"])
        self.assertEqual([{"title": ""}], field["labels"])
        self.assertEqual({}, field["attributes"])
        self.assertEqual([], seen["banners"])

    def test_only_the_ids_the_deployment_created_reach_the_page(self):
        script = _render(
            {},
            CATALOGUE,
            RECORD_FORMS,
            application={"clients": {"created": CREATED}},
        )

        for client_id in CREATED:
            self.assertIn(to_inline_js(client_id)[1:-1], script)


def _toggle(kind: str, value: str, *, checked: bool) -> dict:
    return {
        "tagName": "INPUT",
        "type": kind,
        "name": "service",
        "value": value,
        "checked": checked,
    }


def _carried(field: dict) -> list[str]:
    return [
        carrier["node"]["value"]
        for carrier in field.get("carriers", [])
        if not carrier["node"].get("removed")
    ]


@unittest.skipUnless(shutil.which("node"), "node is not available in PATH")
class TestToggleLock(unittest.TestCase):
    def test_a_radio_group_is_disabled_and_only_its_checked_value_still_posts(self):
        radios = [
            _toggle("radio", "ollama", checked=False),
            _toggle("radio", "libretranslate", checked=True),
        ]
        free, chosen = _managed(fields={"#title": radios})["fields"]["#title"]

        self.assertTrue(free["disabled"])
        self.assertTrue(chosen["disabled"])
        self.assertFalse(chosen["readOnly"])
        self.assertEqual([], _carried(free))
        self.assertEqual(["libretranslate"], _carried(chosen))
        self.assertEqual(
            {"position": "afterend", "type": "hidden", "name": "service"},
            {
                "position": chosen["carriers"][0]["position"],
                "type": chosen["carriers"][0]["node"]["type"],
                "name": chosen["carriers"][0]["node"]["name"],
            },
        )

    def test_a_checkbox_posts_its_value_only_while_checked(self):
        boxes = [
            _toggle("checkbox", "1", checked=True),
            _toggle("checkbox", "1", checked=False),
        ]
        on, off = _managed(fields={"#title": boxes})["fields"]["#title"]

        self.assertTrue(on["disabled"])
        self.assertTrue(off["disabled"])
        self.assertEqual(["1"], _carried(on))
        self.assertEqual([], _carried(off))

    def test_a_rails_checkbox_pair_posts_its_hidden_zero_then_its_checked_value(self):
        for checked, posted in ((False, ["0"]), (True, ["0", "1"])):
            with self.subTest(checked=checked):
                pair = [
                    {
                        "tagName": "INPUT",
                        "type": "hidden",
                        "name": "service",
                        "value": "0",
                    },
                    _toggle("checkbox", "1", checked=checked),
                ]
                hidden, box = _managed(fields={"#title": pair})["fields"]["#title"]

                self.assertTrue(hidden["disabled"])
                self.assertTrue(box["disabled"])
                self.assertEqual(posted, _carried(hidden) + _carried(box))

    def test_a_select_posts_each_selected_value(self):
        select = {"tagName": "SELECT", "name": "languages", "selected": ["de", "en"]}
        field = _managed(fields={"#title": [select]})["fields"]["#title"][0]

        self.assertTrue(field["disabled"])
        self.assertEqual(["de", "en"], _carried(field))

    def test_a_control_without_a_name_gets_no_carrier(self):
        seen = _managed(fields={"#title": ["SELECT"]})

        self.assertTrue(seen["fields"]["#title"][0]["disabled"])
        self.assertEqual([], _carried(seen["fields"]["#title"][0]))
        self.assertNotIn("input", seen["created"])

    def test_the_unlock_removes_the_carrier_so_the_edit_posts_alone(self):
        radio = _toggle("radio", "libretranslate", checked=True)
        field = _managed(
            fields={"#title": [radio]}, dblclick=("#title",), on_label=True
        )["fields"]["#title"][0]

        self.assertFalse(field["disabled"])
        self.assertEqual(1, len(field.get("carriers", [])))
        self.assertEqual([], _carried(field))

    def test_a_secret_toggle_keeps_its_type(self):
        radio = _toggle("radio", "on", checked=True)
        seen = _managed(fields={"#smtp_password": [radio]})
        field = seen["fields"]["#smtp_password"][0]

        self.assertEqual("radio", field["type"])
        self.assertTrue(field["disabled"])


@unittest.skipUnless(shutil.which("node"), "node is not available in PATH")
class TestControlLock(unittest.TestCase):
    def test_a_button_is_disabled_and_carries_nothing(self):
        seen = _managed(fields={"#title": [{"tagName": "BUTTON", "name": "add"}]})
        button = seen["fields"]["#title"][0]

        self.assertTrue(button["disabled"])
        self.assertFalse(button["readOnly"])
        self.assertEqual(f"Managed by the deployment at {TITLE_PATH}", button["title"])
        self.assertNotIn("input", seen["created"])

    def test_an_input_read_only_does_not_hold_is_disabled_and_carried(self):
        color = {"tagName": "INPUT", "type": "color", "name": "accent", "value": "#336"}
        field = _managed(fields={"#title": [color]})["fields"]["#title"][0]

        self.assertTrue(field["disabled"])
        self.assertFalse(field["readOnly"])
        self.assertEqual(["#336"], _carried(field))

    def test_a_control_that_posts_no_value_gets_no_carrier(self):
        controls = [
            {"tagName": "INPUT", "type": "submit", "name": "save", "value": "Save"},
            {"tagName": "INPUT", "type": "file", "name": "logo"},
        ]
        seen = _managed(fields={"#title": controls})

        for field in seen["fields"]["#title"]:
            self.assertTrue(field["disabled"])
            self.assertEqual([], _carried(field))
        self.assertNotIn("input", seen["created"])

    def test_a_textarea_turns_read_only(self):
        field = _managed(fields={"#title": ["TEXTAREA"]})["fields"]["#title"][0]

        self.assertTrue(field["readOnly"])
        self.assertFalse(field["disabled"])


@unittest.skipUnless(shutil.which("node"), "node is not available in PATH")
class TestFieldUnlock(unittest.TestCase):
    def test_one_double_click_frees_every_control_of_the_field(self):
        seen = _managed(
            fields={"#title": ["INPUT", {"tagName": "BUTTON"}]}, dblclick=("#title",)
        )
        text, button = seen["fields"]["#title"]

        self.assertEqual(["Edit anyway?"], seen["confirms"])
        self.assertFalse(text["readOnly"])
        self.assertFalse(button["disabled"])
        self.assertEqual("", button["title"])
        self.assertEqual(1, len(seen["banners"]))
        self.assertIn(TITLE_PATH, seen["banners"][0]["text"])

    def test_a_control_rendered_while_the_field_is_unlocked_stays_free(self):
        seen = _managed(
            fields={"#title": ["INPUT"]},
            dblclick=("#title",),
            then=({"late": {"#title": ["INPUT"]}},),
        )
        first, added = seen["fields"]["#title"]

        self.assertFalse(first["readOnly"])
        self.assertFalse(added["readOnly"])
        self.assertEqual("", added["title"])

    def test_the_unlock_ends_when_the_page_turns_to_another_record(self):
        seen = _routed(
            forms=RECORD_FORMS,
            fields=_client(CREATED[0]),
            page=CONSOLE + CLIENT_HASH,
            dblclick=("#redirects",),
            then=(
                {"values": {"#clientId": CREATED[1]}},
                {"values": {"#clientId": CREATED[0]}},
            ),
        )

        self.assertEqual(["Edit anyway?"], seen["confirms"])
        self.assertTrue(seen["fields"]["#redirects"][0]["readOnly"])

    def test_an_unlock_leaves_a_control_the_page_disabled_itself_disabled(self):
        select = {"tagName": "SELECT", "disabled": True}
        seen = _managed(
            fields={"#title": [select]}, dblclick=("#title",), on_label=True
        )
        field = seen["fields"]["#title"][0]

        self.assertEqual(["Edit anyway?"], seen["confirms"])
        self.assertTrue(field["disabled"])
        self.assertEqual("", field["title"])


if __name__ == "__main__":
    unittest.main()
