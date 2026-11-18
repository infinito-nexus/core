from __future__ import annotations

import copy
import json
import os
import re
import shlex
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from ansible.errors import AnsibleError
from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import filter_loader, lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar

from plugins.lookup.config import LookupModule
from utils.cache import base as cache_base
from utils.cache.files import iter_project_files_with_content, read_text
from utils.cache.reset import _reset_cache_for_tests
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.config import AppConfigKeyError
from utils.roles.applications.converge import values
from utils.roles.applications.forms import is_sso_source
from utils.roles.mapping import (
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)
from utils.templating.ansible import _trust_as_template
from utils.templating.jinja import looks_like_jinja

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
ADDRESS = "https://blog.example.test"
DESIGN_TITLE = "Blog by Example & Partner"
DISCOURSE_OPTION = "discourse_connect"
AI_MODEL = "probe-chat"
AI_ENVIRONMENT = {
    "id": "infinito-litellm",
    "type": "custom",
    "name": "Infinito LiteLLM",
    "apikey": "SYNTH-AI-KEY-1",
    "endpoint": "http://litellm.example.test/v1",
    "models": [{"model": AI_MODEL}],
}
TRANSLATE_ADDON = ROLE / "meta/addons/freedomtranslate-wp.yml"
TRANSLATE_TASKS = ROLE / "tasks/addons/freedomtranslate-wp-stack-host.yml"

filter_loader.add_directory(str(ROLE / "filter_plugins"))


def _vars() -> dict:
    return load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN), default_if_missing={})


def _manager_tasks() -> list[dict]:
    return load_yaml_any(str(ROLE / "tasks/07_manager_ops.yml"), default_if_missing=[])


def _option_tasks() -> list[dict]:
    return load_yaml_any(str(ROLE / "tasks/utils/options.yml"), default_if_missing=[])


def _domain_tasks() -> list[dict]:
    return load_yaml_any(
        str(ROLE / "tasks/08_update_domain.yml"), default_if_missing=[]
    )


def _task(fragment: str, tasks: list[dict] | None = None) -> dict:
    return next(t for t in tasks or _manager_tasks() if fragment in t["name"])


def _option_task(fragment: str) -> dict:
    return _task(fragment, _option_tasks())


def _position(fragment: str, tasks: list[dict] | None = None) -> int:
    return next(
        i for i, t in enumerate(tasks or _manager_tasks()) if fragment in t["name"]
    )


def _render(expression: str, **variables):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(expression))


def _translate_options() -> dict:
    addon = load_yaml_any(str(TRANSLATE_ADDON), default_if_missing={})
    return {
        name: f"https://rendered.example.test/{name}"
        if looks_like_jinja(str(value))
        else value
        for name, value in addon["config"]["options"].items()
    }


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
    "registration": False,
    "multisite": False,
}
CHECKED = "{{ WORDPRESS_OPTIONS_CHECKED }}"


def _resolve(name: str, scenario: dict, expression: str | None = None):
    """Resolve one variable of ``vars/main.yml`` through Ansible's templar.

    Args:
        name: the variable to resolve.
        scenario: ``configured`` is what ``services.wordpress.options``
            resolves to (role default and inventory merged), ``design`` is
            ``services.design.enabled``, ``title`` is ``services.design.title``
            and the design lookup's ``title``, ``translate`` is
            ``addons.freedomtranslate-wp.enabled``, ``translate_options`` is
            that addon's ``config.options``, ``registration`` is the
            ``registration`` login method, ``multisite`` is
            ``services.wordpress.multisite.enabled``, the optional
            ``ai_engine`` is ``addons.ai-engine.enabled`` and the optional
            ``forms`` replaces the role's ``meta/forms.yml``.
        expression: a template to render instead of the variable ``name``.

    Returns:
        The resolved value, with the role's own filter plugins loaded.
    """
    forms = scenario.get("forms") or _forms()
    config = {
        "services.wordpress.options": scenario["configured"],
        "users.platform_administrator.email": ADMIN_EMAIL,
        "services.design.enabled": scenario["design"],
        "addons.freedomtranslate-wp.enabled": scenario["translate"],
        "addons.wp-discourse.config.discourse_settings": [{"name": DISCOURSE_OPTION}],
        "addons.ai-engine.config.environment": AI_ENVIRONMENT,
        "forms": forms,
    }
    application = {
        "services": {
            "design": {"enabled": scenario["design"], "title": scenario["title"]},
            "wordpress": {
                "options": scenario["configured"],
                "address": ADDRESS,
                "login": {
                    "method": {"registration": {"enabled": scenario["registration"]}}
                },
                "multisite": {"enabled": scenario["multisite"]},
            },
        },
        "addons": {
            "freedomtranslate-wp": {
                "enabled": scenario["translate"],
                "config": {"options": scenario["translate_options"]},
            },
            "ai-engine": {
                "enabled": scenario.get("ai_engine", False),
                "config": {"environment": AI_ENVIRONMENT, "default_model": AI_MODEL},
            },
        },
    }
    users = {"platform_administrator": {"email": ADMIN_EMAIL}}
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
    template = _trust_as_template(expression) if expression else declared[name]
    with unittest.mock.patch.object(lookup_loader, "get", side_effect=get):
        return templar.template(template)


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
        match = OPTIONS_LOOKUP.search(_vars()["WORDPRESS_OPTION_PINS_UNREAD"])
        self.assertIsNotNone(
            match, "WORDPRESS_OPTION_PINS_UNREAD must read services.<entity>.options"
        )
        return [term.strip() for term in match.group(1).split(",")]

    def test_the_lookup_carries_no_default(self):
        self.assertEqual(len(self._terms()), 3, "lookup('config', app, path) only")

    def test_the_site_write_receives_the_map_through_the_validating_filter(self):
        task = _task("Converge the managed options of the WordPress site")
        self.assertEqual(task["include_tasks"], "utils/options.yml")
        self.assertEqual(task["vars"]["wordpress_options"], CHECKED)
        self.assertEqual(task["vars"]["wordpress_options_command"], "option")

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
        return _resolve("WORDPRESS_OPTIONS", scenario, CHECKED)

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

    def _unread(self, configured: dict, forms: dict | None = None) -> list[str]:
        scenario = ALL_ON | {"configured": configured}
        if forms:
            scenario["forms"] = forms
        return _resolve("WORDPRESS_OPTION_PINS_UNREAD", scenario)

    def test_a_pin_of_an_option_another_source_manages_is_unread(self):
        for name, value in (
            ("admin_email", "ops@example.test"),
            ("blogname", "Own name"),
            ("freedomtranslate_api_url", "https://translate.example.test/translate"),
        ):
            configured = {"permalink_structure": PINNED_STRUCTURE, name: value}
            with self.subTest(option=name):
                self.assertEqual([name], self._unread(configured))
                self.assertNotEqual(
                    value, self._options(ALL_ON | {"configured": configured})[name]
                )

    def test_a_pin_no_field_reads_is_not_written(self):
        configured = {"permalink_structure": PINNED_STRUCTURE, "blogdescription": "Tag"}
        self.assertEqual(["blogdescription"], self._unread(configured))
        self.assertNotIn(
            "blogdescription", self._options(ALL_ON | {"configured": configured})
        )

    def test_the_role_pins_are_all_read(self):
        self.assertEqual([], self._unread({"permalink_structure": PINNED_STRUCTURE}))

    def test_a_pin_with_an_inventory_field_is_written(self):
        configured = {"permalink_structure": PINNED_STRUCTURE, "blogdescription": "Tag"}
        forms = copy.deepcopy(_forms())
        forms["general"]["fields"]["blogdescription"] = {
            "source": "services.wordpress.options.blogdescription",
            "mode": "enforced",
            "selector": "#blogdescription",
        }
        self.assertEqual([], self._unread(configured, forms))
        self.assertEqual(
            "Tag",
            self._options(ALL_ON | {"configured": configured, "forms": forms})[
                "blogdescription"
            ],
        )

    def test_the_filter_guards_a_field_the_role_writes_elsewhere(self):
        configured = {"permalink_structure": PINNED_STRUCTURE, "home": "https://x"}
        forms = copy.deepcopy(_forms())
        forms["general"]["fields"]["home"] = {
            "source": "services.wordpress.options.home",
            "mode": "enforced",
            "selector": "#home",
        }
        with self.assertRaises(AnsibleError) as caught:
            self._options(ALL_ON | {"configured": configured, "forms": forms})
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
        def fields(*forms: str) -> set[str]:
            return {
                field
                for form in forms
                for field, spec in _forms()[form]["fields"].items()
                if not is_sso_source(spec["source"])
            }

        self.assertEqual(
            fields("general", "permalink", "translate"),
            set(_resolve("WORDPRESS_OPTIONS", ALL_ON)),
        )
        self.assertEqual(
            fields("network"),
            set(_resolve("WORDPRESS_NETWORK_OPTIONS", ALL_ON | {"multisite": True})),
        )

    def test_registration_maps_to_the_option_of_a_single_site(self):
        for registration, stored in ((True, "1"), (False, "0")):
            with self.subTest(registration=registration):
                scenario = ALL_ON | {"registration": registration}
                self.assertEqual(stored, self._options(scenario)["users_can_register"])
                self.assertEqual({}, _resolve("WORDPRESS_NETWORK_OPTIONS", scenario))

    def test_registration_maps_to_the_network_option_under_multisite(self):
        for registration, stored in ((True, "user"), (False, "none")):
            with self.subTest(registration=registration):
                scenario = ALL_ON | {"registration": registration, "multisite": True}
                self.assertEqual(
                    {"registration": stored},
                    _resolve("WORDPRESS_NETWORK_OPTIONS", scenario),
                )
                self.assertNotIn("users_can_register", self._options(scenario))

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
        moved = ["admin_email", "blogname", "users_can_register", *_translate_options()]
        for name in moved:
            with self.subTest(option=name):
                self.assertNotIn(name, owned)

    def test_no_managed_option_is_owned_elsewhere(self):
        owned = _resolve("WORDPRESS_OPTIONS_OWNED_ELSEWHERE", ALL_ON)
        managed = set(_resolve("WORDPRESS_OPTIONS", ALL_ON)) | set(
            _resolve("WORDPRESS_NETWORK_OPTIONS", ALL_ON | {"multisite": True})
        )
        self.assertFalse(set(owned) & managed)


class TestOrder(unittest.TestCase):
    def test_options_are_read_after_the_plugins_are_installed(self):
        self.assertLess(
            _position("Iterate through WordPress plugins"),
            _position("Converge the managed options of the WordPress site"),
        )

    def test_unread_pins_are_refused_before_any_write(self):
        self.assertLess(
            _position("Refuse a services.wordpress.options pin"),
            _position("Converge the managed options of the WordPress site"),
        )

    def test_the_multisite_state_is_checked_before_any_write(self):
        self.assertLess(
            _position("Iterate through WordPress plugins"),
            _position("Detect if WordPress is Multisite"),
        )
        self.assertLess(
            _position("Detect if WordPress is Multisite"),
            _position("Refuse a Multisite state"),
        )
        self.assertLess(
            _position("Refuse a Multisite state"),
            _position("Converge the managed options of the WordPress site"),
        )

    def test_the_translate_readback_follows_the_options_write(self):
        self.assertLess(
            _position("Converge the managed options of the WordPress site"),
            _position("Verify FreedomTranslate"),
        )

    def test_the_drift_report_runs_between_the_read_and_the_write(self):
        tasks = _option_tasks()
        self.assertLess(
            _position("Read the stored WordPress", tasks),
            _position("Report the managed WordPress", tasks),
        )
        self.assertLess(
            _position("Report the managed WordPress", tasks),
            _position("Write each managed WordPress", tasks),
        )


class TestUnreadPins(unittest.TestCase):
    def test_the_refusal_names_the_unread_pins(self):
        task = _task("Refuse a services.wordpress.options pin")
        self.assertEqual(
            ["WORDPRESS_OPTION_PINS_UNREAD | length == 0"],
            task["ansible.builtin.assert"]["that"],
        )
        self.assertIn(
            "WORDPRESS_OPTION_PINS_UNREAD | join(', ')",
            task["ansible.builtin.assert"]["fail_msg"],
        )


class TestNetworkOptions(unittest.TestCase):
    def test_the_network_write_runs_only_with_a_network_option(self):
        task = _task("Converge the managed options of the WordPress network")
        self.assertEqual(task["include_tasks"], "utils/options.yml")
        self.assertEqual(
            task["vars"],
            {
                "wordpress_options": "{{ WORDPRESS_NETWORK_OPTIONS }}",
                "wordpress_options_command": "site option",
            },
        )
        self.assertEqual(task["when"], "WORDPRESS_NETWORK_OPTIONS | length > 0")


class TestSiteAddress(unittest.TestCase):
    def test_both_address_fields_are_the_tls_origin_on_a_single_site(self):
        self.assertEqual(
            {"siteurl": ADDRESS, "home": ADDRESS},
            _resolve("WORDPRESS_ADDRESS", ALL_ON),
        )

    def test_no_address_field_applies_under_multisite(self):
        self.assertEqual(
            {}, _resolve("WORDPRESS_ADDRESS", ALL_ON | {"multisite": True})
        )

    def test_the_domain_update_converges_the_address_through_the_options_task(self):
        tasks = _domain_tasks()
        task = _task("Converge the managed site address", tasks)
        self.assertEqual(task["include_tasks"], "utils/options.yml")
        self.assertEqual(
            task["vars"],
            {
                "wordpress_options": "{{ WORDPRESS_ADDRESS }}",
                "wordpress_options_command": "option",
            },
        )
        self.assertLess(
            _position("Get current 'home' URL", tasks),
            _position("Converge the managed site address", tasks),
        )
        self.assertLess(
            _position("Converge the managed site address", tasks),
            _position("Search-replace old", tasks),
        )

    def test_the_database_rewrite_targets_the_managed_address(self):
        task = _task("Search-replace old", _domain_tasks())
        self.assertEqual(
            "{{ WORDPRESS_ADDRESS.home }}", task["vars"]["wp_new_url_norm"]
        )
        self.assertNotIn("vars", _task("Update Single Side"))

    def test_no_task_writes_the_address_options_by_name(self):
        tasks = read_text(str(ROLE / "tasks/08_update_domain.yml"))
        self.assertNotIn("option update home", tasks)
        self.assertNotIn("option update siteurl", tasks)


class TestManagedOptionsGuard(unittest.TestCase):
    GUARD = ROLE / "files/mu-plugins/infinito-managed-options.php"
    WRITER = ROLE / "files/php/managed_options.php"
    TASK = "Hand the managed option values"

    def test_the_guard_holds_every_option_the_site_converges_and_its_address(self):
        managed = _resolve("WORDPRESS_MANAGED_OPTIONS", ALL_ON)
        self.assertEqual(
            _resolve("WORDPRESS_OPTIONS", ALL_ON, CHECKED)
            | {"siteurl": ADDRESS, "home": ADDRESS},
            managed["option"],
        )
        self.assertEqual({}, managed["site_option"])
        self.assertEqual({}, managed["merge"])

    def test_the_guard_holds_the_network_options_under_multisite(self):
        managed = _resolve(
            "WORDPRESS_MANAGED_OPTIONS",
            ALL_ON | {"multisite": True, "registration": True},
        )
        self.assertEqual({"registration": "user"}, managed["site_option"])
        self.assertNotIn("home", managed["option"])

    def test_the_values_reach_the_container_before_any_wordpress_command(self):
        self.assertEqual(0, _position(self.TASK))
        self.assertLess(_position(self.TASK), _position("Install declared mu-plugins"))

    def test_the_values_travel_on_stdin_and_stay_out_of_the_log(self):
        task = _task(self.TASK)
        command = task["ansible.builtin.shell"]["cmd"]
        self.assertIn("-e INFINITO_MANAGED_OPTIONS", command)
        self.assertNotIn("WORDPRESS_MANAGED_OPTIONS |", command)
        self.assertTrue(
            task["ansible.builtin.shell"]["stdin"].startswith(
                "{{ WORDPRESS_MANAGED_OPTIONS | to_json | b64encode }}\n"
            )
        )
        self.assertEqual("{{ MASK_CREDENTIALS_IN_LOGS | bool }}", task["no_log"])

    def test_the_values_file_is_private_from_its_first_byte(self):
        writer = read_text(str(self.WRITER))
        umask = writer.index("umask(0077);")
        self.assertLess(umask, writer.index("file_put_contents($staged"))
        self.assertIn("chmod($staged, 0600)", writer)
        self.assertIn("rename($staged, $path)", writer)
        self.assertNotRegex(writer, r"echo [^;]*\$(managed|code)")

    def test_the_values_file_is_php_outside_the_mu_plugins(self):
        declared = _vars()
        path = declared["WORDPRESS_MANAGED_OPTIONS_FILE"]
        self.assertIn("'wp-content/infinito-managed-options.php'", path)
        self.assertNotIn("WORDPRESS_MU_PLUGINS_DIR", path)
        env = read_text(str(ROLE / "templates/env.j2"))
        self.assertIn(
            "WORDPRESS_MANAGED_OPTIONS_FILE={{ WORDPRESS_MANAGED_OPTIONS_FILE | dotenv_quote }}",
            env,
        )
        self.assertNotIn("WORDPRESS_MANAGED_OPTIONS |", env)
        self.assertNotIn("WORDPRESS_MANAGED_OPTIONS }}", env)

    def test_the_guard_fails_closed_without_its_values(self):
        guard = read_text(str(self.GUARD))
        check = guard.index("if (!is_array($infinito_managed_options)")
        self.assertLess(check, guard.index("throw new RuntimeException", check))
        self.assertLess(
            guard.index("throw new RuntimeException", check),
            guard.index("add_filter("),
        )
        self.assertIn("getenv('WORDPRESS_MANAGED_OPTIONS_FILE')", guard)

    def test_the_guard_keeps_the_managed_value_for_every_writer(self):
        guard = read_text(str(self.GUARD))
        self.assertIn("'pre_update_option_' . $infinito_managed_name", guard)
        self.assertIn(
            "return is_main_site() ? $infinito_managed_value : $value;", guard
        )
        self.assertIn("'pre_update_site_option_' . $infinito_managed_name", guard)
        self.assertEqual(3, guard.count("PHP_INT_MAX"))


class TestAiEngineLock(unittest.TestCase):
    STACK_HOST = ROLE / "tasks/addons/ai-engine-stack-host.yml"
    READER = ROLE / "files/php/ai_engine/endpoint.php"
    GUARD = TestManagedOptionsGuard.GUARD

    def test_the_guard_keeps_the_gateway_environment_and_the_defaults(self):
        managed = _resolve("WORDPRESS_MANAGED_OPTIONS", ALL_ON | {"ai_engine": True})
        self.assertEqual(
            {
                "mwai_options": {
                    "keys": {
                        "ai_default_env": AI_ENVIRONMENT["id"],
                        "ai_default_model": AI_MODEL,
                    },
                    "records": {"ai_envs": AI_ENVIRONMENT},
                }
            },
            managed["merge"],
        )

    def test_the_form_is_native_and_hides_the_api_key(self):
        form = _forms()["ai_engine"]
        self.assertIs(True, form["native"])
        self.assertEqual(["WORDPRESS_AI_ENGINE"], form["sinks"])
        self.assertEqual("password", form["fields"]["apikey"]["type"])

    def test_the_guard_merges_only_the_managed_record_on_the_main_site(self):
        guard = read_text(str(self.GUARD))
        self.assertIn(
            "return is_main_site() ? infinito_managed_options_merge($value,"
            " $infinito_managed_value) : $value;",
            guard,
        )
        self.assertIn("($entry['id'] ?? null) !== $record['id']", guard)
        self.assertIn("!is_array($infinito_managed_options['merge'] ?? null)", guard)

    def test_the_drift_read_runs_before_the_write_and_leaves_the_api_key_out(self):
        tasks = load_yaml_any(str(self.STACK_HOST), default_if_missing=[])
        read = _position("Read the managed AI Engine settings", tasks)
        self.assertLess(read, _position("Report the managed AI Engine settings", tasks))
        self.assertLess(
            _position("Report the managed AI Engine settings", tasks),
            _position("Point the AI Engine default environment", tasks),
        )
        self.assertNotIn("apikey", read_text(str(self.READER)))

    def test_the_write_carries_the_sink_values(self):
        task = _task(
            "Point the AI Engine default environment",
            load_yaml_any(str(self.STACK_HOST), default_if_missing=[]),
        )
        self.assertIn(
            "{'environment': WORDPRESS_AI_ENGINE_ENVIRONMENT,"
            " 'default_model': WORDPRESS_AI_ENGINE.ai_default_model}",
            task["ansible.builtin.shell"]["stdin"],
        )
        self.assertEqual("{{ MASK_CREDENTIALS_IN_LOGS | bool }}", task["no_log"])


class TestMultisiteState(unittest.TestCase):
    def _holds(self, stdout: str, enabled: bool) -> bool:
        (condition,) = _task("Refuse a Multisite state")["ansible.builtin.assert"][
            "that"
        ]
        return bool(
            _render(
                "{{ (" + condition + ") | bool }}",
                wp_is_multisite={"stdout": stdout},
                WORDPRESS_MULTISITE_ENABLED=enabled,
            )
        )

    def test_an_installation_the_configuration_declares_passes(self):
        self.assertTrue(self._holds("1\n", True))
        self.assertTrue(self._holds("0", False))

    def test_an_installation_the_configuration_contradicts_fails(self):
        self.assertFalse(self._holds("1", False))
        self.assertFalse(self._holds("0\n", True))

    def test_the_refusal_names_both_states(self):
        message = _task("Refuse a Multisite state")["ansible.builtin.assert"][
            "fail_msg"
        ]
        self.assertIn("wp_is_multisite.stdout | trim", message)
        self.assertIn("services.wordpress.multisite.enabled", message)


class TestDriftReport(unittest.TestCase):
    def test_it_hands_the_overwritten_managed_options_to_the_shared_report(self):
        task = _option_task("Report the managed WordPress")
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
        failed_when = _option_task("Read the stored WordPress")["failed_when"]
        return bool(
            _render(
                "{{ (" + failed_when + ") | bool }}",
                wp_options_stored={"rc": rc, "stderr": stderr},
            )
        )

    def test_it_loops_over_the_map_it_receives(self):
        task = _option_task("Read the stored WordPress")
        self.assertEqual(task["loop"], "{{ wordpress_options | dict2items }}")
        self.assertIn("wp {{ wordpress_options_command }} get", task["shell"])
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
    def _argv(self, key: str, value, command: str = "option") -> list[str]:
        rendered = _render(
            _option_task("Write each managed WordPress")["shell"],
            item={"item": {"key": key, "value": value}},
            wordpress_options_command=command,
            WORDPRESS_USER="www-data",
            WORDPRESS_CONTAINER_ADDRESS="wordpress",
            WORDPRESS_DOCKER_HTML_PATH="/var/www/html",
        )
        return shlex.split(rendered)

    def _changed(self, stdout: str) -> bool:
        changed_when = _option_task("Write each managed WordPress")["changed_when"]
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

    def test_a_network_option_reaches_wp_cli_as_a_site_option(self):
        argv = self._argv("registration", "user", "site option")
        position = argv.index("update")
        self.assertEqual(argv[position - 2 : position], ["site", "option"])
        self.assertEqual(argv[position + 1], "registration")
        self.assertEqual(json.loads(argv[position + 2]), "user")

    def test_only_drifted_options_are_written(self):
        task = _option_task("Write each managed WordPress")
        self.assertEqual(task["loop"], "{{ wp_options_stored.results }}")
        self.assertEqual(task["when"], "item | wordpress_option_drifted")
        self.assertEqual(task["register"], "wp_options_written")

    def test_an_updated_option_is_a_change(self):
        self.assertTrue(self._changed("Success: Updated 'blogname' option."))

    def test_a_value_wordpress_already_stores_sanitized_is_no_change(self):
        self.assertFalse(
            self._changed("Success: Value passed for 'blogname' option is unchanged.")
        )
        self.assertFalse(
            self._changed(
                "Success: Value passed for 'registration' site option is unchanged."
            )
        )


class TestFlushTask(unittest.TestCase):
    def _flushes(self, written: dict) -> bool:
        when = _option_task("Flush the rewrite rules")["when"]
        return bool(_render("{{ (" + when + ") | bool }}", wp_options_written=written))

    def test_a_write_flushes_the_rewrite_rules(self):
        self.assertIn(
            "wp rewrite flush", _option_task("Flush the rewrite rules")["shell"]
        )
        self.assertTrue(self._flushes({"changed": True, "results": []}))

    def test_no_write_leaves_the_rewrite_rules_alone(self):
        self.assertFalse(self._flushes({"changed": False, "skipped": True}))


if __name__ == "__main__":
    unittest.main()
