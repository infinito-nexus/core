from __future__ import annotations

import importlib.util
import re
import unittest
import unittest.mock as mock

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.roles.mapping import (
    ROLE_FILE_META_CSP,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TEMPL_COMPOSE,
)

from . import PROJECT_ROOT

APP = "web-app-decidim"
ROLE = PROJECT_ROOT / "roles" / APP
PROVIDER_HOST = "api.seaweedfs.s3.example.com"
CLEARNET = "decidim.example.com"
ONION = "decidim." + "a" * 56 + ".onion"
SERVICES = load_yaml(str(ROLE / ROLE_FILE_META_SERVICES))
INITIALIZER = ROLE / "files" / "ruby" / "initializers" / "same_origin_storage.rb"
VERIFIED_DECIDIM = "0.31.6"
BLOB_PROXY = "active_storage/blobs/proxy#show"
REPRESENTATION_PROXY = "active_storage/representations/proxy#show"


def _objstore(served_on: list[str]) -> dict:
    """
    Args:
        served_on: the domains the node serves Decidim under.

    Returns:
        lookup('objstore', 'web-app-decidim') for a shared seaweedfs with a clearnet API domain and the role's own `public` flag.
    """
    spec = importlib.util.spec_from_file_location(
        "lookup_objstore_decidim", str(PROJECT_ROOT / "plugins/lookup/objstore.py")
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
            "web-svc-seaweedfs": {
                "services": {"seaweedfs": {"name": "seaweedfs"}},
                "domains": {"canonical": {"api": PROVIDER_HOST}},
            },
        },
        "domains": {APP: served_on},
        "tls": {"domain": served_on[0], "protocols": {"web": "http"}},
    }
    lookup = module.LookupModule()
    lookup._templar = mock.MagicMock(available_variables={})
    lookup._loader = mock.MagicMock()
    with (
        mock.patch.object(module, "lookup_loader") as loader,
        mock.patch.object(module, "entity_name", return_value="decidim"),
    ):
        loader.get.side_effect = lambda name, **_kwargs: mock.MagicMock(
            run=lambda _terms, **_kw: [payloads[name]]
        )
        return lookup.run(
            [APP], variables={"DIR_COMPOSITIONS": "/opt/compose/", "TLS_ENABLED": True}
        )[0]


def _render_env(origin: str, objstore: dict) -> dict[str, str]:
    """
    Args:
        origin: the app origin lookup('tls', app, 'url.origin') yields on the node.
        objstore: the objstore lookup payload.

    Returns:
        The rendered env file of the role as a key to value mapping.
    """
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
        keep_trailing_newline=True,
    )
    tls = {"url.origin": origin, "url.base": origin + "/", "enabled": False}

    def lookup(name: str, *terms: str):
        if name == "objstore":
            return objstore[terms[1]]
        if name == "tls":
            return tls[terms[1]]
        if name in ("database", "engine"):
            return "x"
        if name == "email":
            return {"enabled": False}
        if name == "debug":
            return False
        raise AssertionError(f"env.j2 renders an unexpected lookup {name}{terms}")

    env.globals["lookup"] = lookup
    env.filters["bool"] = bool
    env.filters["dotenv_quote"] = lambda value: value
    env.filters["regex_replace"] = lambda value, pattern, repl: re.sub(
        pattern, repl, value
    )
    rendered = env.get_template(f"roles/{APP}/templates/env.j2").render(
        application_id=APP,
        HOST_TIMEZONE="UTC",
        ENVIRONMENT="production",
        DECIDIM_SECRET_KEY_BASE="kb",
        DECIDIM_ORGANIZATION_NAME="Org",
        DECIDIM_OIDC_ENABLED=False,
    )
    return dict(
        line.split("=", 1)
        for line in rendered.splitlines()
        if "=" in line and not line.startswith("#")
    )


def _prepended_routes() -> list[tuple[str, str]]:
    """
    Returns:
        The routes the initializer prepends under the ActiveStorage prefix as path and controller action, in their order.
    """
    block = re.search(
        r"(?ms)^Rails\.application\.routes\.prepend do\n  scope ActiveStorage\.routes_prefix do\n(.*?)\n  end\nend$",
        read_text(str(INITIALIZER)),
    )
    return re.findall(r'get "([^"]+)" => "([^"]+)"', block.group(1))


def _first_pattern(path: str) -> str:
    """
    Args:
        path: a request path below the ActiveStorage prefix.

    Returns:
        The first prepended route pattern that matches the path, the one the Rails router picks.
    """
    for pattern, _ in _prepended_routes():
        expression = re.sub(
            r"\\\*\w+", ".+", re.sub(r":\w+", "[^/]+", re.escape(pattern))
        )
        if re.fullmatch(expression, path):
            return pattern
    raise AssertionError(f"no prepended route takes {path}")


class TestDecidimSameOriginEnv(unittest.TestCase):
    SCENARIOS = (
        ("clearnet", "https://" + CLEARNET, [CLEARNET]),
        ("onion", "http://" + ONION, [ONION]),
    )

    def test_uploads_are_addressed_on_the_app_origin(self):
        for label, origin, served_on in self.SCENARIOS:
            with self.subTest(network=label):
                values = _render_env(origin, _objstore(served_on))

                self.assertEqual(
                    values["STORAGE_CDN_HOST"],
                    origin,
                    "Decidim::AssetRouter::Storage builds Active Storage URLs "
                    "through the Rails routes only while Decidim.storage_cdn_host "
                    "is set; without it a processed variant resolves to the S3 "
                    "service URL",
                )

    def test_no_env_value_names_the_provider_host(self):
        for label, origin, served_on in self.SCENARIOS:
            with self.subTest(network=label):
                values = _render_env(origin, _objstore(served_on))

                leaks = {k: v for k, v in values.items() if PROVIDER_HOST in v}
                self.assertEqual(leaks, {})

    def test_the_server_side_endpoint_is_the_internal_store(self):
        values = _render_env("https://" + CLEARNET, _objstore([CLEARNET]))

        self.assertEqual(values["AWS_ENDPOINT"], "http://seaweedfs:8333")


class TestDecidimSameOriginInitializer(unittest.TestCase):
    def test_redirect_routes_serve_through_the_proxy(self):  # nocheck: test.text-presence -- tokenizes the file into commands or directives; the rule taints tokenizer output  # fmt: skip
        actions = dict(_prepended_routes())
        for path, action in (
            ("/blobs/redirect/SIGNED/logo.png", BLOB_PROXY),
            ("/blobs/proxy/SIGNED/logo.png", BLOB_PROXY),
            ("/blobs/SIGNED/logo.png", BLOB_PROXY),
            (
                "/representations/redirect/SIGNED/VARIANT/logo.png",
                REPRESENTATION_PROXY,
            ),
            ("/representations/proxy/SIGNED/VARIANT/logo.png", REPRESENTATION_PROXY),
            ("/representations/SIGNED/VARIANT/logo.png", REPRESENTATION_PROXY),
        ):
            with self.subTest(path=path):
                self.assertEqual(actions[_first_pattern(path)], action)

    def test_each_path_shape_takes_the_route_of_its_own_shape(self):  # nocheck: test.text-presence -- simulates Rails first-match routing over the parsed route table  # fmt: skip
        for path, pattern in (
            ("/blobs/proxy/SIGNED/logo.png", "/blobs/proxy/:signed_id/*filename"),
            ("/blobs/redirect/SIGNED/logo.png", "/blobs/redirect/:signed_id/*filename"),
            ("/blobs/SIGNED/logo.png", "/blobs/:signed_id/*filename"),
            (
                "/representations/proxy/SIGNED/VARIANT/logo.png",
                "/representations/proxy/:signed_blob_id/:variation_key/*filename",
            ),
            (
                "/representations/redirect/SIGNED/VARIANT/logo.png",
                "/representations/redirect/:signed_blob_id/:variation_key/*filename",
            ),
            (
                "/representations/SIGNED/VARIANT/logo.png",
                "/representations/:signed_blob_id/:variation_key/*filename",
            ),
        ):
            with self.subTest(path=path):
                self.assertEqual(_first_pattern(path), pattern)

    def test_decidim_version_is_the_verified_one(self):
        self.assertEqual(
            SERVICES["decidim"]["version"],
            VERIFIED_DECIDIM,
            "re-verify the initializer's SIGNATURES and Decidim::AssetRouter::Storage "
            "against the activestorage and decidim-core this image ships, then "
            "move VERIFIED_DECIDIM",
        )


class TestDecidimNoBrowserPathToTheStore(unittest.TestCase):
    def test_csp_allows_no_object_store_connection(self):
        self.assertNotIn("web-svc-seaweedfs", read_text(str(ROLE / ROLE_FILE_META_CSP)))

    def test_compose_pins_no_object_store_host(self):
        self.assertNotIn(
            "web-svc-seaweedfs", read_text(str(ROLE / ROLE_FILE_TEMPL_COMPOSE))
        )


if __name__ == "__main__":
    unittest.main()
