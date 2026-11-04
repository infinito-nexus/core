"""``services.wordpress.options`` is the one place the role pins WordPress options.

The permalink structure is pinned to the format the blog published its post
URLs under, the vars read the map through a strict config lookup, every option
the role writes through another path is refused by name, and the tasks in
``tasks/07_manager_ops.yml`` read each option, write only the ones that drift
and flush the rewrite rules after a write.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import tempfile
import unittest
from pathlib import Path

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from plugins.lookup.config import LookupModule
from utils.cache import _reset_cache_for_tests
from utils.cache import base as cache_base
from utils.cache.files import iter_project_files_with_content, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.config import AppConfigKeyError
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN
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


def _vars() -> dict:
    return load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN), default_if_missing={})


def _manager_tasks() -> list[dict]:
    return load_yaml_any(str(ROLE / "tasks/07_manager_ops.yml"), default_if_missing=[])


def _task(fragment: str) -> dict:
    return next(t for t in _manager_tasks() if fragment in t["name"])


def _render(expression: str, **variables):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(expression))


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

    def test_install_time_and_addon_options_are_owned(self):
        owned = _vars()["WORDPRESS_OPTIONS_OWNED_ELSEWHERE"]
        for name in ("home", "siteurl", "blogname", "admin_email", "active_plugins"):
            with self.subTest(option=name):
                self.assertIn(f"'{name}'", owned)
        self.assertIn("addons.wp-discourse.config.discourse_settings", owned)


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
