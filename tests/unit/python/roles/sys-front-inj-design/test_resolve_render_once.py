from __future__ import annotations

import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

from ansible.errors import AnsibleUndefinedVariable
from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import filter_loader, lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar, trust_as_template

from plugins.lookup.cdn import _cdn_paths, _to_url_tree
from plugins.lookup.tls import LookupModule as TlsLookup
from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.domains.default_primary import default_domain_primary
from utils.networks.reachability import CLEARNET, TOR, network_of
from utils.roles.mapping import (
    ROLE_FILE_DEFAULTS_MAIN,
    ROLE_FILE_TASKS_MAIN,
    ROLE_FILE_VARS_MAIN,
)

filter_loader.add_directory(str(PROJECT_ROOT / "plugins" / "filter"))

DESIGN_DIR = PROJECT_ROOT / "roles" / "sys-front-inj-design"
TASKS = DESIGN_DIR / ROLE_FILE_TASKS_MAIN
DOMAIN = default_domain_primary()
ONION = "a" * 56 + ".onion"
CDN_ROOT = "/nonexistent/infinito/cdn"
CDN_BASE = {CLEARNET: f"https://cdn.{DOMAIN}", TOR: f"http://cdn.{ONION}"}
APPS = (
    "web-svc-logout",
    "web-app-openbao",
    "web-app-xwiki",
    "web-app-mastodon",
    "web-app-wordpress",
)

LEGACY_OVERLAY = load_yaml_str(
    r"""
- vars:
    _app_style_css: >-
      {{ (lookup('template', _app_compose_src) | trim | replace(_cdn_origin, '/'))
         if (app_body_css ~ app_logo_css) | length > 0 else '' }}
  set_fact:
    app_style_present: "{{ _app_style_css | length > 0 }}"
- vars:
    _design_configured: "{{ 'INFINITO_DESIGN' in design_body_js }}"  # nocheck: JS marker in the embedded legacy task, not an environment key
    _design_js: >-
      {{ (lookup('template', _design_compose_src) | trim)
         if _design_configured | bool else design_body_js }}
  set_fact:
    design_config_json: "{{ (lookup('template', _design_config_src) | trim) if _design_configured | bool else '' }}"
    design_js_one_liner: "{{ (_design_js | to_one_liner) if _design_js | length > 0 else '' }}"
"""
)


class _Stub(LookupBase):
    def __init__(self, answer):
        super().__init__()
        self._answer = answer

    def run(self, terms, variables=None, **kwargs):
        return [self._answer(variables or {}, *terms)]


def _cdn(variables, application_id):
    base = CDN_BASE[network_of(variables["domain"])]
    paths = _cdn_paths(CDN_ROOT, application_id, "latest")
    return {**paths, "urls": _to_url_tree(paths, paths["root"], base)}


def _design(logo):
    def answer(variables, application_id):
        base = _cdn(variables, application_id)["urls"]["role"]["release"]["img"]
        return {
            "logo": "/repo/logo.svg" if logo else False,
            "title": "Brand" if logo else False,
            "slots": {"header": {"width": 120, "height": 40}},
            "urls": {
                "favicon_ico": f"{base}/design/favicon.ico",
                "header": {"png": f"{base}/design/header.png"},
            },
        }

    return answer


def resolve_tasks():
    """Return the two resolve tasks of the role as loaded from disk.

    Returns:
        ``[style_task, script_task]`` in file order.
    """
    tasks = load_yaml_any(str(TASKS))
    return [t for t in tasks if str(t.get("name", "")).startswith("🔍 Resolve")]


def legacy_tasks():
    """Return the resolve tasks with their pre-change expressions restored.

    Returns:
        ``[style_task, script_task]`` with the legacy vars and facts overlaid.
    """
    legacy = []
    for task, overlay in zip(resolve_tasks(), LEGACY_OVERLAY, strict=True):
        legacy.append(
            {
                **task,
                "vars": {**task["vars"], **overlay["vars"]},
                "set_fact": {**task["set_fact"], **overlay["set_fact"]},
            }
        )
    return legacy


def _trusted(value):
    if isinstance(value, str):
        return trust_as_template(value)
    if isinstance(value, dict):
        return {key: _trusted(item) for key, item in value.items()}
    return value


def run_tasks(tasks, app, vhost, logo, root=PROJECT_ROOT):
    """Template the set_fact arguments of both resolve tasks in order.

    Args:
        tasks: the two resolve tasks, current or legacy.
        app: the application_id being injected.
        vhost: the vhost being rendered, clearnet or onion.
        logo: whether the branding replaces the logo and title.
        root: the playbook directory the role paths resolve against.

    Returns:
        ``(facts, renders)``: the facts both tasks set and, per task, a
        ``Counter`` of rendered template paths relative to ``root``.
    """
    tree = {app: [f"x.app.{DOMAIN}", f"x.app.{ONION}"]}
    stubs = {
        "domains": lambda _v, *terms: tree[terms[0]] if terms else tree,
        "cdn": _cdn,
        "design": _design(logo),
    }
    renders: list[Counter] = []
    real_get = lookup_loader.get

    def get(name, *args, **kwargs):
        if name == "tls":
            lookup = TlsLookup()
            lookup._loader = kwargs.get("loader")
            lookup._templar = None
            return lookup
        if name in stubs:
            return _Stub(stubs[name])
        plugin = real_get(name, *args, **kwargs)
        if name == "template":
            original = plugin.run

            def counted(terms, variables=None, **options):
                renders[-1].update(str(Path(t).relative_to(root)) for t in terms)
                return original(terms, variables=variables, **options)

            plugin.run = counted
        return plugin

    loader = DataLoader()
    variables = {
        **loader.load_from_file(
            str(DESIGN_DIR / ROLE_FILE_DEFAULTS_MAIN), trusted_as_template=True
        ),
        **loader.load_from_file(
            str(DESIGN_DIR / ROLE_FILE_VARS_MAIN), trusted_as_template=True
        ),
    }
    app_vars = PROJECT_ROOT / "roles" / app / ROLE_FILE_VARS_MAIN
    if app == "web-app-xwiki":
        xwiki = loader.load_from_file(str(app_vars), trusted_as_template=True)
        variables.update(XWIKI_URL=xwiki["XWIKI_URL"], XWIKI_CORE_VERSION="0.0.0")
    variables.update(
        playbook_dir=str(root),
        application_id=app,
        domain=vhost,
        TLS_ENABLED=True,
        TLS_MODE="letsencrypt",
        design_css_states={},
    )
    facts: dict = {}
    with mock.patch.object(lookup_loader, "get", side_effect=get):
        for task in tasks:
            renders.append(Counter())
            scope = {**variables, **facts, **_trusted(task["vars"])}
            templar = Templar(loader=DataLoader(), variables=scope)
            facts.update(templar.template(_trusted(task["set_fact"])))
    return facts, renders


VARIANTS = [
    (app, vhost, logo)
    for app in APPS
    for vhost in (f"x.app.{DOMAIN}", f"x.app.{ONION}")
    for logo in (True, False)
]

STYLE = "roles/web-svc-logout/files/style.css"
APP_CSS = "roles/sys-front-inj-design/templates/css/app.css.j2"
SCRIPT = "roles/web-svc-logout/templates/design.js.j2"
DESIGN_JS = "roles/sys-front-inj-design/templates/js/design.js.j2"
CONFIG = "roles/sys-front-inj-design/templates/js/design-config.json.j2"


class TestFactsMatchThePreviousExpressions(unittest.TestCase):
    def test_every_variant_sets_byte_identical_facts(self) -> None:
        current, legacy = resolve_tasks(), legacy_tasks()
        for app, vhost, logo in VARIANTS:
            with self.subTest(app=app, vhost=vhost, logo=logo):
                facts, _ = run_tasks(current, app, vhost, logo)
                expected, _ = run_tasks(legacy, app, vhost, logo)
                self.assertEqual(facts, expected)
                self.assertEqual(
                    {k: type(v) for k, v in facts.items()},
                    {k: type(v) for k, v in expected.items()},
                )

    def test_the_variants_cover_sheet_logo_script_and_neither(self) -> None:
        seen = {}
        for app in APPS:
            facts, _ = run_tasks(resolve_tasks(), app, f"x.app.{ONION}", True)
            seen[app] = (
                facts["app_style_present"],
                bool(facts["design_config_json"]),
                bool(facts["design_js_one_liner"]),
            )
        self.assertEqual(seen["web-app-wordpress"], (False, False, False))
        self.assertEqual(seen["web-app-mastodon"], (False, False, True))
        self.assertEqual(seen["web-svc-logout"], (True, True, True))
        self.assertTrue(seen["web-app-xwiki"][0])

    def test_the_onion_sheet_names_no_clearnet_vhost(self) -> None:
        facts, _ = run_tasks(resolve_tasks(), "web-app-xwiki", f"x.app.{ONION}", False)
        self.assertIn(f"http://x.app.{ONION}/resources/icons/", facts["app_style_css"])
        self.assertNotIn(f"x.app.{DOMAIN}", facts["app_style_css"])


class TestEachTemplateRendersOncePerFact(unittest.TestCase):
    def test_the_composed_sheet_and_script_render_once(self) -> None:
        _, renders = run_tasks(
            resolve_tasks(), "web-svc-logout", f"x.app.{DOMAIN}", True
        )
        self.assertEqual(renders[0], Counter({STYLE: 2, APP_CSS: 1}))
        self.assertEqual(renders[1], Counter({SCRIPT: 2, DESIGN_JS: 1, CONFIG: 1}))

    def test_the_previous_expressions_render_repeatedly(self) -> None:
        _, renders = run_tasks(
            legacy_tasks(), "web-svc-logout", f"x.app.{DOMAIN}", True
        )
        self.assertGreater(renders[0][APP_CSS], 1)
        self.assertGreater(renders[0][STYLE], 2)
        self.assertGreater(sum(renders[1].values()), 4)


class TestABrokenRoleSheetStaysLoud(unittest.TestCase):
    def test_an_undefined_variable_fails_naming_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "roles" / "web-app-broken" / "files").mkdir(parents=True)
            (root / "roles" / "web-app-broken" / "files" / "style.css").write_text(
                "body { color: {{ undefined_in_sheet }}; }\n", encoding="utf-8"
            )
            (root / "roles" / "sys-front-inj-design").mkdir(parents=True)
            (root / "roles" / "sys-front-inj-design" / "templates").symlink_to(
                DESIGN_DIR / "templates"
            )
            for label, tasks in (
                ("current", resolve_tasks()),
                ("legacy", legacy_tasks()),
            ):
                with (
                    self.subTest(tasks=label),
                    self.assertRaisesRegex(
                        AnsibleUndefinedVariable, "undefined_in_sheet"
                    ),
                ):
                    run_tasks(tasks, "web-app-broken", f"x.app.{DOMAIN}", True, root)

    def test_the_failing_task_names_its_application(self) -> None:
        for task in resolve_tasks():
            with self.subTest(task=task["name"]):
                self.assertIn("{{ application_id }}", task["name"])


if __name__ == "__main__":
    unittest.main()
