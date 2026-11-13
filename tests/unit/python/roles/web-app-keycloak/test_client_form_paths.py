import json
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar
from jinja2 import (
    ChainableUndefined,
    Environment,
    FileSystemLoader,
    Undefined,
    select_autoescape,
)
from jinja2.nativetypes import NativeEnvironment

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_FORMS, ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles/web-app-keycloak"
CLIENT_TEMPLATE = ROLE / "templates/import/clients/default.json.j2"


def _at(node, path):
    for key in path:
        node = node.get(key) if isinstance(node, dict) else None
    return node


def _to_json(value):
    return json.dumps(None if isinstance(value, Undefined) else value)


class TestClientFormPaths(unittest.TestCase):
    def test_every_client_form_field_names_its_place_in_the_client(self):
        form = load_yaml_any(str(ROLE / ROLE_FILE_META_FORMS))["client"]
        role_vars = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
        values = {field: f"<{field}>" for field in form["fields"]}
        native = NativeEnvironment()
        sinks = {
            name: native.from_string(role_vars[name]).render(
                KEYCLOAK_CLIENT=values, lookup=lambda *_: values, application_id=""
            )
            for name in form["sinks"]
        }
        env = Environment(
            loader=FileSystemLoader(str(CLIENT_TEMPLATE.parent)),
            undefined=ChainableUndefined,
            autoescape=select_autoescape(),
        )
        env.filters.update(to_json=_to_json, bool=bool)
        client = json.loads(
            env.get_template(CLIENT_TEMPLATE.name).render(lookup=lambda *_: "", **sinks)
        )
        paths = role_vars["KEYCLOAK_CLIENT_FORM_PATHS"]
        self.assertEqual(
            {field: _at(client, path) for field, path in paths.items()}, values
        )

    def test_the_read_spec_holds_only_the_clients_of_the_form_record(self):
        record = load_yaml_any(str(ROLE / ROLE_FILE_META_FORMS))["client"]["record"]
        declared = DataLoader().load_from_file(
            str(ROLE / ROLE_FILE_VARS_MAIN), trusted_as_template=True
        )
        self.assertIn(f"'{record['source']}'", declared["KEYCLOAK_CLIENT_FORM_IDS"])
        clients = [{"clientId": "cymais.cloud"}, {"clientId": "account"}]
        templar = Templar(
            loader=DataLoader(),
            variables={
                **declared,
                "KEYCLOAK_SETTINGS_SPEC": {"clients": clients},
                "KEYCLOAK_CLIENT_FORM_IDS": ["cymais.cloud"],
            },
        )
        self.assertEqual(
            templar.template(declared["KEYCLOAK_SETTINGS_READ_SPEC"]),
            {"clients": clients[:1], "fields": declared["KEYCLOAK_CLIENT_FORM_PATHS"]},
        )


if __name__ == "__main__":
    unittest.main()
