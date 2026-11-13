from __future__ import annotations

import json
import re
import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications import sso_fields
from utils.roles.mapping import ROLE_FILE_META_FORMS

APP = "web-app-joomla"
ROLE = PROJECT_ROOT / "roles" / APP
PLUGIN = (
    ROLE / "files/joomla-oidc-plugin/plg_system_keycloak/src/Extension/Keycloak.php"
)
ADDON = ROLE / "meta/addons/plg_system_keycloak.yml"
FORMS = ROLE / ROLE_FILE_META_FORMS
ENV = ROLE / "templates/env.j2"
ENV_KEY = "JOOMLA_OIDC_PROFILE_LOCKED"
MARKER = "data-infinito-sso-locked"
SELECTOR_ID = re.compile(r"#(jform_\w+)\[" + re.escape(MARKER) + r"\]")
COLUMN = re.compile(
    r"'(\w+)'\s*=>\s*\['field'\s*=>\s*'(\w+)',\s*'column'\s*=>\s*'\w+'\]"
)
PARAM = re.compile(r"'(\w+)'\s*=>\s*'(\w+)'")
ADDRESS = re.compile(r"const LOCKED_ADDRESS = '(\w+)';")


def _locked() -> dict[str, str]:
    return sso_fields.selectors(load_yaml_any(FORMS))


def _constant(source: str, name: str) -> str:
    return re.search(rf"const {name} = \[(.*?)\];", source, re.DOTALL).group(1)


def _locked_by_the_plugin(key: str) -> set[str]:
    source = read_text(str(PLUGIN))
    columns = dict(COLUMN.findall(_constant(source, "LOCKED_COLUMNS")))
    params = dict(PARAM.findall(_constant(source, "LOCKED_PARAMS")))
    profile = load_yaml_any(ADDON)["config"]["profile"]
    if key in columns:
        return {f"jform_{columns[key]}"}
    if key in params:
        return {f"jform_params_{params[key]}"}
    if key == ADDRESS.search(source).group(1):
        return {f"jform_profile_{field}" for field in profile["address"]}
    if key in profile["claims"]:
        return {f"jform_profile_{key}"}
    return set()


def _rendered_env_keys() -> list[str]:
    line = next(
        line
        for line in read_text(str(ENV)).splitlines()
        if line.startswith(f"{ENV_KEY}=")
    )
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )

    def lookup(name: str, *terms: str):
        if (name, *terms) == ("field_locks", APP):
            return {"profile": _locked()}
        raise AssertionError(f"{ENV_KEY} renders an unexpected lookup {name}{terms}")

    env.globals["lookup"] = lookup
    env.filters["to_json"] = json.dumps
    env.filters["dotenv_quote"] = lambda value: value
    rendered = env.from_string(line).render(application_id=APP)
    return json.loads(rendered.split("=", 1)[1])


class TestProfileLockFields(unittest.TestCase):
    def test_every_locked_key_locks_the_fields_its_selector_decorates(self):
        mismatched = {
            key: (
                sorted(_locked_by_the_plugin(key)),
                sorted(SELECTOR_ID.findall(selector)),
            )
            for key, selector in _locked().items()
            if _locked_by_the_plugin(key) != set(SELECTOR_ID.findall(selector))
        }
        self.assertEqual({}, mismatched)

    def test_every_locked_key_names_a_field_the_plugin_locks(self):
        self.assertEqual(
            [], [key for key in _locked() if not _locked_by_the_plugin(key)]
        )

    def test_the_container_receives_every_locked_key(self):
        self.assertEqual(list(_locked()), _rendered_env_keys())

    def test_every_selector_matches_only_marked_fields(self):
        unmarked = [
            part.strip()
            for selector in _locked().values()
            for part in selector.split(",")
            if not SELECTOR_ID.fullmatch(part.strip())
        ]
        self.assertEqual([], unmarked)


if __name__ == "__main__":
    unittest.main()
