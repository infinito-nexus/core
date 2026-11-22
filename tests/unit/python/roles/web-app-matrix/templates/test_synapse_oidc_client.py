from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jinja2 import ChainableUndefined, Environment, FileSystemLoader, select_autoescape

from utils.cache.yaml import load_yaml_any, load_yaml_tagged
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

APPLICATION_ID = "web-app-matrix"
ROLE = PROJECT_ROOT / "roles" / APPLICATION_ID
FLAVORS = {
    "compose": (
        "templates/flavor/compose/synapse/homeserver.yaml.j2",
        "oidc_providers",
    ),
    "ansible": (
        "templates/flavor/ansible/vars.yml.j2",
        "matrix_synapse_oidc_providers",
    ),
}
SHARED_CLIENT_ID = "example.com"
SECRET = "s3cret"
OIDC = {
    "BUTTON_TEXT": "SSO Login (EXAMPLE.COM)",
    "CLIENT": {
        "ID": SHARED_CLIENT_ID,
        "SECRET": SECRET,
        "ISSUER_URL": "https://auth.example.com/realms/example.com",
    },
    "ATTRIBUTES": {"USERNAME": "preferred_username", "NAME": "name", "EMAIL": "email"},
}


def services_config(path: str):
    """Resolve ``lookup('config', 'web-app-matrix', path)`` for a ``services.*`` path.

    Args:
        path: dotted path below the role's config, starting with ``services.``.
    """
    node = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES))
    for key in path.removeprefix("services.").split("."):
        node = node[key]
    return node


def lookup(name, *args, **_kwargs):
    """Answer the role's own SSO config and leave every other lookup undefined.

    Args:
        name: the lookup plugin the template asked for.
    """
    if (
        name == "config"
        and args[:1] == (APPLICATION_ID,)
        and args[1].startswith("services.sso.")
    ):
        return services_config(args[1])
    return ChainableUndefined(name=f"lookup('{name}')")


def environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(ROLE)),
        trim_blocks=True,
        undefined=ChainableUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["bool"] = lambda value: value is True or str(value).lower() == "true"
    env.filters["to_json"] = lambda value: json.dumps(value, default=str)
    env.filters["urlsplit"] = lambda _value, _part=None: ""
    env.filters["network_of"] = lambda _value: "clearnet"
    env.filters["combine"] = lambda *_args, **_kwargs: {}
    return env


def role_var(name: str):
    """Render one variable of the role's ``vars/main.yml`` with the stubbed lookups.

    Args:
        name: the variable.
    """
    expression = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))[name]
    return (
        environment()
        .from_string(expression)
        .render(lookup=lookup, application_id=APPLICATION_ID)
    )


def oidc_provider(flavor: str) -> dict:
    """Render one Synapse flavor and return its single OIDC provider.

    Args:
        flavor: ``compose`` or ``ansible``.
    """
    template, key = FLAVORS[flavor]
    rendered = (
        environment()
        .get_template(template)
        .render(
            lookup=lookup,
            application_id=APPLICATION_ID,
            OIDC=OIDC,
            MATRIX_OIDC_ENABLED=True,
            MATRIX_OIDC_HOST_IS_ONION=False,
            MATRIX_OIDC_CLIENT_ID=role_var("MATRIX_OIDC_CLIENT_ID"),
            MATRIX_BRIDGES=[],
        )
    )
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / f"{flavor}.yml"
        path.write_text(rendered)
        (provider,) = load_yaml_tagged(path)[key]
    return provider


class TestSynapseLogsInThroughItsOwnClient(unittest.TestCase):
    def test_both_flavors_log_in_through_the_synapse_client(self) -> None:
        client_id = services_config("services.sso.oidc.clients.web")
        self.assertNotEqual(client_id, SHARED_CLIENT_ID)
        for flavor in FLAVORS:
            with self.subTest(flavor=flavor):
                self.assertEqual(oidc_provider(flavor)["client_id"], client_id)

    def test_both_flavors_receive_backchannel_logout_tokens(self) -> None:
        for flavor in FLAVORS:
            with self.subTest(flavor=flavor):
                self.assertIs(oidc_provider(flavor)["backchannel_logout_enabled"], True)

    def test_both_flavors_keep_the_provider_existing_accounts_are_linked_to(
        self,
    ) -> None:
        for flavor in FLAVORS:
            with self.subTest(flavor=flavor):
                provider = oidc_provider(flavor)
                self.assertEqual(provider["idp_id"], "keycloak")
                self.assertIs(provider["allow_existing_users"], True)

    def test_both_flavors_authenticate_with_the_shared_secret(self) -> None:
        for flavor in FLAVORS:
            with self.subTest(flavor=flavor):
                self.assertEqual(oidc_provider(flavor)["client_secret"], SECRET)


if __name__ == "__main__":
    unittest.main()
