"""``WORDPRESS_OPTIONS`` is the one map the role pins WordPress options from.

The map joins the options ``meta/forms.yml`` manages (``admin_email``, the
design title as ``blogname``, ``permalink_structure`` and the FreedomTranslate
options), each read from its field's ``source`` through
``lookup('form_values', ...)``, with ``services.wordpress.options`` as the
strict config lookup resolves it; a pin that contradicts a managed option is
refused. Every option another path writes is refused by name, and the tasks
in ``tasks/07_manager_ops.yml`` read each option, report the managed ones an
admin changed, write only the ones that drift and flush the rewrite rules
after a write that changed the stored value.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shlex
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ansible.errors import AnsibleError
from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import filter_loader, lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar

from plugins.lookup.config import LookupModule
from utils.cache import _reset_cache_for_tests
from utils.cache import base as cache_base
from utils.cache.files import iter_project_files_with_content, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.config import AppConfigKeyError
from utils.roles.applications.converge import values
from utils.roles.mapping import (
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)
from utils.templating.ansible import _trust_as_template

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles/web-app-wordpress"
PROBE_APP = "web-app-options-probe"
PINNED_STRUCTURE = "/blog/%year%/%monthnum%/%day%/%postname%/"
OPTIONS_LOOKUP = re.compile(r"lookup\(([^()]*'\.options')\)")
LITERAL_OPTION_WRITE = re.compile(
    r"wp option (?:update|add) ([a-z_][a-z0-9_]*)\b"
    r"|update_option\(\s*'([a-z_][a-z0-9_]*)'"
)
ADMIN_EMAIL = "admin@example.test"
DESIGN_TITLE = "Blog by Example & Partner"
DISCOURSE_OPTION = "discourse_connect"
TRANSLATE_ADDON = ROLE / "meta/addons/freedomtranslate-wp.yml"
TRANSLATE_TASKS = ROLE / "tasks/addons/freedomtranslate-wp-stack-host.yml"

filter_loader.add_directory(str(ROLE / "filter_plugins"))


def _vars() -> dict:
    return load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN), default_if_missing={})


def _manager_tasks() -> list[dict]:
    return load_yaml_any(str(ROLE / "tasks/07_manager_ops.yml"), default_if_missing=[])


def _task(fragment: str) -> dict:
    return next(t for t in _manager_tasks() if fragment in t["name"])


def _position(fragment: str) -> int:
    return next(i for i, t in enumerate(_manager_tasks()) if fragment in t["name"])


def _render(expression: str, **variables):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(expression))


def _translate_options() -> dict:
    addon = load_yaml_any(str(TRANSLATE_ADDON), default_if_missing={})
    return addon["config"]["options"]


def _forms() -> dict:
    return load_yaml_any(str(ROLE / ROLE_FILE_META_FORMS), default_if_missing={})


class _Stub(LookupBase):
    def __init__(self, answer):
        super().__init__()
        self._answer = answer

    def run(self, terms, variables=None, **kwargs):
        return [self._answer(*terms)]


ALL_ON = {
    "configured": {"permalink_structure": PINNED_STRUCTURE},
    "design": True,
    "title": DESIGN_TITLE,
    "translate": True,
    "translate_options": _translate_options(),
}


def _resolve(name: str, scenario: dict):
    """Resolve one variable of ``vars/main.yml`` through Ansible's templar.

    Args:
        name: the variable to resolve.
        scenario: ``configured`` is what ``services.wordpress.options``
            resolves to (role default and inventory merged), ``design`` is
            ``services.design.enabled``, ``title`` is ``services.design.title``
            and the design lookup's ``title``, ``translate`` is
            ``addons.freedomtranslate-wp.enabled``, ``translate_options`` is
            that addon's ``config.options`` and the optional ``forms``
            replaces the role's ``meta/forms.yml``.

    Returns:
        The resolved value, with the role's own filter plugins loaded and
        ``lookup('form_values', ...)`` answered by ``converge.values`` over
        the role's forms.
    """
    config = {
        "services.wordpress.options": scenario["configured"],
        "users.platform_administrator.email": ADMIN_EMAIL,
        "services.design.enabled": scenario["design"],
        "addons.freedomtranslate-wp.enabled": scenario["translate"],
        "addons.wp-discourse.config.discourse_settings": [{"name": DISCOURSE_OPTION}],
    }
    application = {
        "services": {
            "design": {"enabled": scenario["design"], "title": scenario["title"]},
            "wordpress": {"options": scenario["configured"]},
        },
        "addons": {
            "freedomtranslate-wp": {
                "enabled": scenario["translate"],
                "config": {"options": scenario["translate_options"]},
            }
        },
    }
    users = {"platform_administrator": {"email": ADMIN_EMAIL}}
    forms = scenario.get("forms") or _forms()
    stubs = {
        "config": lambda _app, path: config[path],
        "design": lambda _app: {"title": scenario["title"]},
        "form_values": lambda _app, form: values(form, forms, application, users),
    }
    real_get = lookup_loader.get

    def get(lookup_name, *args, **kwargs):
        if lookup_name in stubs:
            return _Stub(stubs[lookup_name])
        return real_get(lookup_name, *args, **kwargs)

    declared = DataLoader().load_from_file(
        str(ROLE / ROLE_FILE_VARS_MAIN), trusted_as_template=True
    )
    templar = Templar(
        loader=DataLoader(), variables={**declared, "entity_name": "wordpress"}
    )
    with mock.patch.object(lookup_loader, "get", side_effect=get):
        return templar.template(declared[name])


def _messages(error: BaseException) -> str:
    parts = []
    while error is not None:
        parts.append(str(error))
        error = error.__cause__ or error.__context__
    return "\n".join(parts)


class TestPinnedStructure(unittest.TestCase):
    def test_services_pins_the_structure_of_the_published_urls(self):
        services = load_yaml_any(
            str(ROLE / ROLE_FILE_META_SERVICES), default_if_missing={}
        )
        self.assertEqual(
            services["wordpress"]["options"]["permalink_structure"], PINNED_STRUCTURE
        )

    def test_the_hard_coded_structure_is_gone(self):
        self.assertNotIn("WORDPRESS_PERMALINK_STRUCTURE", _vars())
        self.assertNotIn(
            "WORDPRESS_PERMALINK_STRUCTURE",
            read_text(str(ROLE / "tasks/07_manager_ops.yml")),
        )


class TestStrictLookup(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()
        cache_base._reset()
        self._cwd = str(Path.cwd())
        self._tmpdir = tempfile.TemporaryDirectory()
        os.chdir(self._tmpdir.name)

    def tearDown(self) -> None:
        os.chdir(self._cwd)
        self._tmpdir.cleanup()
        _reset_cache_for_tests()

    def _terms(self) -> list[str]:
        match = OPTIONS_LOOKUP.search(_vars()["WORDPRESS_OPTIONS"])
        self.assertIsNotNone(
            match, "WORDPRESS_OPTIONS must read services.<entity>.options"
        )
        return [term.strip() for term in match.group(1).split(",")]

    def test_the_lookup_carries_no_default(self):
        self.assertEqual(len(self._terms()), 3, "lookup('config', app, path) only")

    def test_the_vars_pass_the_map_through_the_validating_filter(self):
        self.assertRegex(
            _vars()["WORDPRESS_OPTIONS"],
            r"\| wordpress_options_checked\(WORDPRESS_OPTIONS_OWNED_ELSEWHERE\)",
        )

    def _path(self) -> str:
        return _render("{{ " + self._terms()[2] + " }}", entity_name="wordpress")

    def test_a_missing_options_key_fails_loudly(self):
        applications = {PROBE_APP: {"services": {"wordpress": {"enabled": True}}}}
        with self.assertRaises(AppConfigKeyError) as caught:
            LookupModule().run(
                [PROBE_APP, self._path()], variables={"applications": applications}
            )
        self.assertIn("options", str(caught.exception))

    def test_a_present_options_key_resolves(self):
        options = {"permalink_structure": PINNED_STRUCTURE}
        applications = {PROBE_APP: {"services": {"wordpress": {"options": options}}}}
        out = LookupModule().run(
            [PROBE_APP, self._path()], variables={"applications": applications}
        )
        self.assertEqual(out, [options])

    def test_the_role_default_resolves_without_an_inventory_entry(self):
        out = LookupModule().run(
            ["web-app-wordpress", self._path()],
            variables={"applications": {"web-app-wordpress": {}}},
        )
        self.assertEqual(out[0]["permalink_structure"], PINNED_STRUCTURE)


class TestEffectiveMap(unittest.TestCase):
    def _options(self, scenario: dict) -> dict:
        return _resolve("WORDPRESS_OPTIONS", scenario)

    def test_the_role_default_stays_in_the_map(self):
        self.assertEqual(self._options(ALL_ON)["permalink_structure"], PINNED_STRUCTURE)

    def test_admin_email_is_the_platform_administrators(self):
        self.assertEqual(self._options(ALL_ON)["admin_email"], ADMIN_EMAIL)

    def test_the_design_title_is_the_blogname_while_the_design_is_on(self):
        self.assertEqual(self._options(ALL_ON)["blogname"], DESIGN_TITLE)

    def test_no_blogname_while_the_design_is_off(self):
        self.assertNotIn("blogname", self._options(ALL_ON | {"design": False}))

    def test_a_boolean_design_title_is_refused_while_the_design_is_on(self):
        for title in (False, True):
            with self.subTest(title=title), self.assertRaises(AnsibleError) as caught:
                self._options(ALL_ON | {"title": title})
            self.assertIn("blogname", _messages(caught.exception))

    def test_the_translate_options_join_while_the_addon_is_on(self):
        options = self._options(ALL_ON)
        declared = _translate_options()
        self.assertTrue(declared, "the addon must declare its options")
        for name, value in declared.items():
            with self.subTest(option=name):
                self.assertEqual(options[name], value)

    def test_no_translate_option_while_the_addon_is_off(self):
        options = self._options(ALL_ON | {"translate": False})
        for name in _translate_options():
            with self.subTest(option=name):
                self.assertNotIn(name, options)

    def test_an_addon_option_no_form_declares_is_not_written(self):
        extra = _translate_options() | {"freedomtranslate_cache": "1"}
        self.assertNotIn(
            "freedomtranslate_cache",
            self._options(ALL_ON | {"translate_options": extra}),
        )

    def test_a_pin_that_contradicts_a_managed_option_is_refused(self):
        for name, value in (
            ("admin_email", "ops@example.test"),
            ("blogname", "Own name"),
            ("freedomtranslate_api_url", "https://translate.example.test/translate"),
        ):
            configured = {"permalink_structure": PINNED_STRUCTURE, name: value}
            with self.subTest(option=name), self.assertRaises(AnsibleError) as caught:
                self._options(ALL_ON | {"configured": configured})
            message = _messages(caught.exception)
            self.assertIn(f"services.wordpress.options.{name}", message)
            self.assertIn("meta/forms.yml", message)

    def test_a_pin_equal_to_its_managed_option_passes(self):
        configured = {"permalink_structure": PINNED_STRUCTURE, "blogname": DESIGN_TITLE}
        self.assertEqual(
            self._options(ALL_ON | {"configured": configured})["blogname"],
            DESIGN_TITLE,
        )

    def test_an_option_no_form_manages_is_written_as_pinned(self):
        configured = {"permalink_structure": PINNED_STRUCTURE, "blogdescription": "Tag"}
        self.assertEqual(
            self._options(ALL_ON | {"configured": configured})["blogdescription"], "Tag"
        )

    def test_the_filter_guards_the_merged_map(self):
        configured = {"permalink_structure": PINNED_STRUCTURE, "home": "https://x"}
        with self.assertRaises(AnsibleError) as caught:
            self._options(ALL_ON | {"configured": configured})
        self.assertIn("services.wordpress.options.home", _messages(caught.exception))

    def test_a_secret_named_managed_option_is_refused(self):
        forms = copy.deepcopy(_forms())
        forms["translate"]["fields"]["freedomtranslate_api_key"] = {
            "source": "addons.freedomtranslate-wp.config.options.freedomtranslate_api_key",
            "mode": "enforced",
            "selector": "#key",
        }
        leaked = _translate_options() | {"freedomtranslate_api_key": "x"}
        with self.assertRaises(AnsibleError) as caught:
            self._options(ALL_ON | {"translate_options": leaked, "forms": forms})
        self.assertIn("freedomtranslate_api_key", _messages(caught.exception))

    def test_every_pinned_default_is_managed_from_its_own_pin(self):
        services = load_yaml_any(
            str(ROLE / ROLE_FILE_META_SERVICES), default_if_missing={}
        )
        sources = {
            field: spec["source"]
            for block in _forms().values()
            for field, spec in block["fields"].items()
        }
        for name in services["wordpress"]["options"]:
            with self.subTest(option=name):
                self.assertEqual(
                    sources.get(name), f"services.wordpress.options.{name}"
                )

    def test_the_managed_options_are_the_fields_of_meta_forms(self):
        fields = {field for block in _forms().values() for field in block["fields"]}
        self.assertEqual(fields, set(_resolve("WORDPRESS_OPTIONS_MANAGED", ALL_ON)))

    def test_no_option_is_declared_by_two_forms(self):
        names = [field for block in _forms().values() for field in block["fields"]]
        self.assertEqual(len(names), len(set(names)))


class TestOwnedElsewhere(unittest.TestCase):
    def test_every_option_the_role_writes_by_name_is_refused_by_the_map(self):
        owned = _vars()["WORDPRESS_OPTIONS_OWNED_ELSEWHERE"]
        written: set[str] = set()
        for _path, content in iter_project_files_with_content(
            extensions=(".yml", ".php"), exclude_tests=True
        ):
            if not str(_path).startswith(str(ROLE)):
                continue
            for match in LITERAL_OPTION_WRITE.finditer(content):
                written.add(match.group(1) or match.group(2))
        self.assertTrue(written, "the scan must find the role's own option writes")
        for name in sorted(written):
            with self.subTest(option=name):
                self.assertIn(f"'{name}'", owned)

    def test_computed_and_wordpress_managed_options_stay_owned(self):
        owned = _resolve("WORDPRESS_OPTIONS_OWNED_ELSEWHERE", ALL_ON)
        for name in (
            "home",
            "siteurl",
            "active_plugins",
            "rewrite_rules",
            "openid_connect_generic_settings",
            "mwai_options",
            "site_icon",
            "site_logo",
            DISCOURSE_OPTION,
        ):
            with self.subTest(option=name):
                self.assertIn(name, owned)

    def test_options_the_map_now_carries_left_the_owned_list(self):
        owned = _resolve("WORDPRESS_OPTIONS_OWNED_ELSEWHERE", ALL_ON)
        moved = ["admin_email", "blogname", *_translate_options()]
        for name in moved:
            with self.subTest(option=name):
                self.assertNotIn(name, owned)

    def test_no_managed_option_is_owned_elsewhere(self):
        owned = _resolve("WORDPRESS_OPTIONS_OWNED_ELSEWHERE", ALL_ON)
        managed = _resolve("WORDPRESS_OPTIONS_MANAGED", ALL_ON)
        self.assertFalse(set(owned) & set(managed))

    def test_the_contributed_map_is_gone(self):
        self.assertNotIn("WORDPRESS_OPTIONS_CONTRIBUTED", _vars())
        self.assertNotIn("WORDPRESS_TRANSLATE_OPTIONS", _vars())


class TestOrder(unittest.TestCase):
    def test_options_are_read_after_the_plugins_are_installed(self):
        self.assertLess(
            _position("Iterate through WordPress plugins"),
            _position("Read the WordPress options"),
        )

    def test_the_translate_readback_follows_the_options_write(self):
        self.assertLess(
            _position("Write each pinned WordPress option"),
            _position("Verify FreedomTranslate"),
        )

    def test_the_drift_report_runs_between_the_read_and_the_write(self):
        self.assertLess(
            _position("Read the WordPress options"),
            _position("Report the managed WordPress options"),
        )
        self.assertLess(
            _position("Report the managed WordPress options"),
            _position("Write each pinned WordPress option"),
        )


class TestDriftReport(unittest.TestCase):
    def test_it_hands_the_overwritten_managed_options_to_the_shared_report(self):
        task = _task("Report the managed WordPress options")
        self.assertEqual(
            task["include_tasks"],
            "{{ lookup('path_absolute', 'tasks/utils/forms/drift.yml') }}",
        )
        self.assertEqual(
            task["vars"]["forms_drift_current"],
            "{{ wp_options_stored.results | wordpress_options_overwritten("
            "lookup('config', application_id, 'forms')) }}",
        )


class TestTranslateReadback(unittest.TestCase):
    def test_the_addon_task_installs_the_plugin_and_writes_no_option(self):
        tasks = load_yaml_any(str(TRANSLATE_TASKS), default_if_missing=[])
        self.assertEqual(
            [t["vars"]["plugin_name"] for t in tasks], ["freedomtranslate-wp"]
        )
        self.assertNotIn("wp option", read_text(str(TRANSLATE_TASKS)))

    def test_the_readback_runs_only_with_the_addon(self):
        self.assertEqual(
            _task("Verify FreedomTranslate")["when"],
            "WORDPRESS_TRANSLATE_ENABLED | bool",
        )

    def test_the_expected_endpoint_follows_the_effective_map(self):
        self.assertEqual(
            _resolve("WORDPRESS_TRANSLATE_ENDPOINT", ALL_ON),
            _translate_options()["freedomtranslate_api_url"],
        )
        own = "https://translate.example.test/translate"
        overridden = _translate_options() | {"freedomtranslate_api_url": own}
        self.assertEqual(
            _resolve(
                "WORDPRESS_TRANSLATE_ENDPOINT",
                ALL_ON | {"translate_options": overridden},
            ),
            own,
        )


class TestReadTask(unittest.TestCase):
    def _fails(self, rc: int, stderr: str) -> bool:
        failed_when = _task("Read the WordPress options")["failed_when"]
        return bool(
            _render(
                "{{ (" + failed_when + ") | bool }}",
                wp_options_stored={"rc": rc, "stderr": stderr},
            )
        )

    def test_it_loops_over_the_validated_map(self):
        task = _task("Read the WordPress options")
        self.assertEqual(task["loop"], "{{ WORDPRESS_OPTIONS | dict2items }}")
        self.assertIn("--format=json", task["shell"])
        self.assertIs(task["changed_when"], False)

    def test_a_missing_option_is_no_failure(self):
        self.assertFalse(
            self._fails(
                1, "Error: Could not get 'blogdescription' option. Does it exist?"
            )
        )

    def test_any_other_error_fails_the_deploy(self):
        self.assertTrue(
            self._fails(1, "Error: Error establishing a database connection.")
        )

    def test_a_present_option_is_no_failure(self):
        self.assertFalse(self._fails(0, ""))


class TestWriteTask(unittest.TestCase):
    def _argv(self, key: str, value) -> list[str]:
        rendered = _render(
            _task("Write each pinned WordPress option")["shell"],
            item={"item": {"key": key, "value": value}},
            WORDPRESS_USER="www-data",
            WORDPRESS_CONTAINER_ADDRESS="wordpress",
            WORDPRESS_DOCKER_HTML_PATH="/var/www/html",
        )
        return shlex.split(rendered)

    def _changed(self, stdout: str) -> bool:
        changed_when = _task("Write each pinned WordPress option")["changed_when"]
        return bool(
            _render(
                "{{ (" + changed_when + ") | bool }}",
                wp_options_written={"stdout": stdout},
            )
        )

    def test_the_structure_reaches_wp_cli_as_one_json_argument(self):
        argv = self._argv("permalink_structure", PINNED_STRUCTURE)
        position = argv.index("update")
        self.assertEqual(argv[position + 1], "permalink_structure")
        self.assertEqual(json.loads(argv[position + 2]), PINNED_STRUCTURE)
        self.assertIn("--format=json", argv)

    def test_a_structure_with_quotes_and_spaces_survives_the_shell(self):
        value = {"title": 'It\'s "quoted" text', "items": [1, "two words"]}
        argv = self._argv("plugin_settings", value)
        position = argv.index("update")
        self.assertEqual(json.loads(argv[position + 2]), value)

    def test_only_drifted_options_are_written(self):
        task = _task("Write each pinned WordPress option")
        self.assertEqual(task["loop"], "{{ wp_options_stored.results }}")
        self.assertEqual(task["when"], "item | wordpress_option_drifted")
        self.assertEqual(task["register"], "wp_options_written")

    def test_an_updated_option_is_a_change(self):
        self.assertTrue(self._changed("Success: Updated 'blogname' option."))

    def test_a_value_wordpress_already_stores_sanitized_is_no_change(self):
        self.assertFalse(
            self._changed("Success: Value passed for 'blogname' option is unchanged.")
        )


class TestFlushTask(unittest.TestCase):
    def _flushes(self, written: dict) -> bool:
        when = _task("Flush the rewrite rules")["when"]
        return bool(_render("{{ (" + when + ") | bool }}", wp_options_written=written))

    def test_a_write_flushes_the_rewrite_rules(self):
        self.assertIn("wp rewrite flush", _task("Flush the rewrite rules")["shell"])
        self.assertTrue(self._flushes({"changed": True, "results": []}))

    def test_no_write_leaves_the_rewrite_rules_alone(self):
        self.assertFalse(self._flushes({"changed": False, "skipped": True}))


if __name__ == "__main__":
    unittest.main()
