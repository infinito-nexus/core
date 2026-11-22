from __future__ import annotations

import importlib.util
import unittest
import unittest.mock as mock

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_SERVICES

APP = "web-app-mastodon"
PROVIDER = "web-svc-seaweedfs"
PROVIDER_HOST = "api.seaweedfs.s3.example.com"
ONION_HOST = "microblog." + "a" * 56 + ".onion"
CLEARNET_HOST = "microblog.example.com"
SERVICES = load_yaml(str(PROJECT_ROOT / "roles" / APP / ROLE_FILE_META_SERVICES))
WEB_SCHEME = {PROVIDER: "https", ONION_HOST: "http", CLEARNET_HOST: "https"}


def _objstore(served_on: list[str]) -> dict:
    """
    Args:
        served_on: the domains the node serves Mastodon on.

    Returns:
        lookup('objstore', 'web-app-mastodon') with the role's own seaweedfs flags.
    """
    spec = importlib.util.spec_from_file_location(
        "lookup_objstore_mastodon", str(PROJECT_ROOT / "plugins/lookup/objstore.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    payloads = {
        "applications": {
            APP: {
                "services": {
                    "seaweedfs": {
                        "enabled": True,
                        "shared": True,
                        "public": SERVICES["seaweedfs"]["public"],
                    }
                },
                "secrets": {"credentials": {"objstore_secret_key": "sk"}},
            },
            PROVIDER: {
                "services": {"seaweedfs": {"name": "seaweedfs"}},
                "domains": {"canonical": {"api": PROVIDER_HOST}},
            },
        },
        "domains": {APP: served_on},
        "tls": {
            "domain": served_on[0],
            "protocols": {"web": WEB_SCHEME[served_on[0]]},
        },
    }
    lookup = module.LookupModule()
    lookup._templar = mock.MagicMock(available_variables={})
    lookup._loader = mock.MagicMock()
    with (
        mock.patch.object(module, "lookup_loader") as loader,
        mock.patch.object(module, "entity_name", return_value="mastodon"),
    ):
        loader.get.side_effect = lambda name, **_kwargs: mock.MagicMock(
            run=lambda _terms, **_kw: [payloads[name]]
        )
        return lookup.run(
            [APP], variables={"DIR_COMPOSITIONS": "/opt/compose/", "TLS_ENABLED": True}
        )[0]


def _render_env(objstore: dict, served_on: list[str]) -> dict[str, str]:
    """
    Args:
        objstore: the resolved objstore payload of the consumer.
        served_on: the domains the node serves Mastodon on.

    Returns:
        Each rendered ``KEY=value`` line of the Mastodon env file.
    """
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
        keep_trailing_newline=True,
    )
    served_scheme = {APP: WEB_SCHEME[served_on[0]], PROVIDER: WEB_SCHEME[PROVIDER]}

    def lookup(name: str, *terms: str):
        if name == "objstore":
            return objstore[terms[1]]
        if name == "tls" and terms[1:] == ("protocols.web",):
            return served_scheme[terms[0]]
        if name == "domain":
            return served_on[0]
        if name == "domains":
            return served_on
        if name in ("config", "database", "engine"):
            return "value"
        if name == "debug":
            return False
        if name == "email":
            return {"enabled": False}
        raise AssertionError(f"env.j2 renders an unexpected lookup {name}{terms}")

    env.globals["lookup"] = lookup
    env.filters["bool"] = bool
    env.filters["dotenv_quote"] = lambda value: value
    rendered = env.get_template(f"roles/{APP}/templates/env.j2").render(
        application_id=APP,
        HOST_TIMEZONE="UTC",
        MASTODON_ALLOWED_PRIVATE_ADDRESSES="",
        POSTGRES_ALLOWED_AVG_CONNECTIONS=5,
        MASTODON_OIDC_ENABLED=False,
    )
    return dict(
        line.split("=", 1)
        for line in rendered.splitlines()
        if "=" in line and not line.startswith("#")
    )


def _media_base_url(values: dict[str, str]) -> str:
    """
    Args:
        values: the rendered Mastodon env.

    Returns:
        The base URL Paperclip's ``:s3_alias_url`` prefixes every upload with.
    """
    return f"{values['S3_PROTOCOL']}://{values['S3_ALIAS_HOST']}"


class TestMastodonS3AliasUrl(unittest.TestCase):
    def test_an_onion_only_node_links_uploads_over_the_onion_scheme(self):
        served_on = [ONION_HOST]
        objstore = _objstore(served_on)

        values = _render_env(objstore, served_on)

        self.assertEqual(
            _media_base_url(values),
            f"http://{ONION_HOST}/_infinito/objstore/mastodon",
            "the onion service maps no port 443, and tor closes the whole "
            "rendezvous circuit on a stream to an unmapped port, so one https "
            "upload link kills every other request of the page in flight",
        )
        self.assertEqual(_media_base_url(values), objstore["public_url"])

    def test_a_clearnet_node_keeps_the_provider_scheme(self):
        served_on = [CLEARNET_HOST]
        objstore = _objstore(served_on)

        values = _render_env(objstore, served_on)

        self.assertEqual(_media_base_url(values), f"https://{PROVIDER_HOST}/mastodon")
        self.assertEqual(_media_base_url(values), objstore["public_url"])


if __name__ == "__main__":
    unittest.main()
