from __future__ import annotations

import importlib.util
import unittest
import unittest.mock as mock

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

APP = "web-app-wordpress"
PROVIDER_HOST = "api.seaweedfs.s3.example.com"
SERVED_ON = ["blog.example.com", "blog." + "a" * 56 + ".onion"]
SERVICES = load_yaml(str(PROJECT_ROOT / "roles" / APP / ROLE_FILE_META_SERVICES))


def _objstore() -> dict:
    """
    Returns:
        lookup('objstore', 'web-app-wordpress') for a node serving the blog on clearnet and onion, with the role's own `public` flag.
    """
    spec = importlib.util.spec_from_file_location(
        "lookup_objstore_wordpress", str(PROJECT_ROOT / "plugins/lookup/objstore.py")
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
        "domains": {APP: SERVED_ON},
    }
    lookup = module.LookupModule()
    lookup._templar = mock.MagicMock(available_variables={})
    lookup._loader = mock.MagicMock()
    with (
        mock.patch.object(module, "lookup_loader") as loader,
        mock.patch.object(module, "entity_name", return_value="wordpress"),
    ):
        loader.get.side_effect = lambda name, **_kwargs: mock.MagicMock(
            run=lambda _terms, **_kw: [payloads[name]]
        )
        return lookup.run(
            [APP], variables={"DIR_COMPOSITIONS": "/opt/compose/", "TLS_ENABLED": True}
        )[0]


def _render_env(objstore: dict) -> dict[str, str]:
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
        keep_trailing_newline=True,
    )

    def lookup(name: str, *terms: str):
        if name == "objstore":
            return objstore[terms[1]]
        if name == "database":
            return "db"
        raise AssertionError(f"env.j2 renders an unexpected lookup {name}{terms}")

    env.globals["lookup"] = lookup
    env.filters["bool"] = bool
    env.filters["dotenv_quote"] = lambda value: value
    env.filters["urlsplit"] = lambda _url, _part: "sso.example.com"
    env.filters["network_of"] = lambda _host: "clearnet"
    rendered = env.get_template(f"roles/{APP}/templates/env.j2").render(
        application_id=APP,
        HOST_TIMEZONE="UTC",
        WORDPRESS_MCP_SERVICE_KEY="wordpress",
        WORDPRESS_NETWORK_BASE_URLS="",
        MODE_DEBUG=False,
        OIDC={"CLIENT": {"ISSUER_URL": "https://sso.example.com/realms/x"}},
    )
    return dict(
        line.split("=", 1)
        for line in rendered.splitlines()
        if "=" in line and not line.startswith("#")
    )


class TestWordpressS3PublicUrl(unittest.TestCase):
    def test_the_bucket_url_is_host_relative(self):
        values = _render_env(_objstore())

        self.assertEqual(
            values["WORDPRESS_S3_PUBLIC_URL"],
            "/_infinito/objstore/wordpress",
            "S3-Uploads prefixes every upload URL with S3_UPLOADS_BUCKET_URL "
            "verbatim, and one container serves the clearnet and the onion "
            "vhost, so only a host-relative path keeps the logo on the page's "
            "network",
        )
        self.assertFalse(values["WORDPRESS_S3_PUBLIC_URL"].startswith("//"))

    def test_no_browser_facing_value_names_the_provider_host(self):
        values = _render_env(_objstore())

        self.assertNotIn(PROVIDER_HOST, values["WORDPRESS_S3_PUBLIC_URL"])

    def test_the_server_side_endpoint_stays_on_the_internal_store(self):
        values = _render_env(_objstore())

        self.assertEqual(values["WORDPRESS_S3_ENDPOINT"], "http://seaweedfs:8333")


if __name__ == "__main__":
    unittest.main()
