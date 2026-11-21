from __future__ import annotations

import json
import re
import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications import sso_fields
from utils.roles.mapping import ROLE_FILE_META_FORMS

from . import PROJECT_ROOT

APP = "web-app-wordpress"
ROLE = PROJECT_ROOT / "roles" / APP
MAPPER = ROLE / "files/mu-plugins/infinito-oidc-rbac-mapper.php"
FORMS = ROLE / ROLE_FILE_META_FORMS
ENV = ROLE / "templates/env.j2"
ENV_KEY = "WORDPRESS_OIDC_PROFILE_LOCKED"
FORM = "body.infinito-sso-managed #your-profile"
LOCKABLE = re.compile(
    r"const INFINITO_OIDC_LOCKABLE_FIELDS = array\((.*?)\n\);", re.DOTALL
)
ENTRY = re.compile(
    r"'(\w+)' => array\('(?:column|meta)' => '\w+', 'input' => '(\w+)', "
    r"'submit' => '(?:restore|drop)'\)"
)


def _locked() -> dict[str, str]:
    return sso_fields.selectors(load_yaml_any(FORMS))


def _input_by_key() -> dict[str, str]:
    return dict(ENTRY.findall(LOCKABLE.search(read_text(str(MAPPER))).group(1)))


def _decorated_input(selector: str) -> str:
    return re.fullmatch(rf"{re.escape(FORM)} #(\w+)", selector).group(1)


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
    def test_every_locked_key_resets_the_input_its_selector_decorates(self):
        inputs = _input_by_key()
        mismatched = {
            key: (inputs.get(key), _decorated_input(selector))
            for key, selector in _locked().items()
            if inputs.get(key) != _decorated_input(selector)
        }
        self.assertEqual({}, mismatched)

    def test_every_lockable_entry_parses(self):
        source = LOCKABLE.search(read_text(str(MAPPER))).group(1)
        self.assertEqual(
            source.count("=> array("), len(_input_by_key()), "unparsed entry"
        )

    def test_the_container_receives_every_locked_key(self):
        self.assertEqual(list(_locked()), _rendered_env_keys())


if __name__ == "__main__":
    unittest.main()
