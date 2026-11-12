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
DECIDIM_0_31_6 = {
    ("Decidim::ContentRenderers::BlobRenderer", "blob_url"): [
        ("req", "blob"),
        ("opt", "variation"),
    ],
    ("Decidim::ContentRenderers::BlobRenderer", "local_blob_url"): [
        ("req", "blob"),
        ("opt", "variation"),
    ],
}
PREPENDED_ROUTES = [
    ("/blobs/redirect/:signed_id/*filename", "active_storage/blobs/proxy#show"),
    ("/blobs/proxy/:signed_id/*filename", "active_storage/blobs/proxy#show"),
    ("/blobs/:signed_id/*filename", "active_storage/blobs/proxy#show"),
    (
        "/representations/redirect/:signed_blob_id/:variation_key/*filename",
        "active_storage/representations/proxy#show",
    ),
    (
        "/representations/proxy/:signed_blob_id/:variation_key/*filename",
        "active_storage/representations/proxy#show",
    ),
    (
        "/representations/:signed_blob_id/:variation_key/*filename",
        "active_storage/representations/proxy#show",
    ),
]
ACTIVESTORAGE_7_2_2_2 = {
    ("S3Service", "url_for_direct_upload"): [
        ("req", "key"),
        ("keyreq", "expires_in"),
        ("keyreq", "content_type"),
        ("keyreq", "content_length"),
        ("keyreq", "checksum"),
        ("key", "custom_metadata"),
    ],
    ("DiskService", "url_for_direct_upload"): [
        ("req", "key"),
        ("keyreq", "expires_in"),
        ("keyreq", "content_type"),
        ("keyreq", "content_length"),
        ("keyreq", "checksum"),
        ("key", "custom_metadata"),
    ],
    ("S3Service", "headers_for_direct_upload"): [
        ("req", "key"),
        ("keyreq", "content_type"),
        ("keyreq", "checksum"),
        ("key", "filename"),
        ("key", "disposition"),
        ("key", "custom_metadata"),
        ("keyrest", "**"),
    ],
    ("S3Service", "upload"): [
        ("req", "key"),
        ("req", "io"),
        ("key", "checksum"),
        ("key", "filename"),
        ("key", "content_type"),
        ("key", "disposition"),
        ("key", "custom_metadata"),
        ("keyrest", "**"),
    ],
}


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
        MODE_DEBUG=False,
        DECIDIM_SECRET_KEY_BASE="kb",
        DECIDIM_ORGANIZATION_NAME="Org",
        DECIDIM_OIDC_ENABLED=False,
    )
    return dict(
        line.split("=", 1)
        for line in rendered.splitlines()
        if "=" in line and not line.startswith("#")
    )


def _initializer_signatures() -> dict[tuple[str, str], list[tuple[str, str]]]:
    """
    Returns:
        The parameter lists the initializer's boot guard expects, keyed by class and method; ActiveStorage service classes by their bare name.
    """
    entries = re.findall(
        r"\[([\w:]+), :(\w+)\] => \[(.*?)\n    \]",
        read_text(str(INITIALIZER)),
        flags=re.DOTALL,
    )
    return {
        (owner.removeprefix("ActiveStorage::Service::"), method): re.findall(
            r"\[:(\w+), :(\w+|\*\*)\]", body
        )
        for owner, method, body in entries
    }


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
    def test_active_storage_routes_proxy_through_the_app(self):
        self.assertRegex(
            read_text(str(INITIALIZER)),
            r"(?m)^Rails\.application\.config\.active_storage\.resolve_model_to_route = :rails_storage_proxy$",
        )

    def test_direct_uploads_go_to_the_same_origin_disk_route(self):
        source = read_text(str(INITIALIZER))

        self.assertIn("update_rails_disk_service_path(token)", source)
        self.assertIn("purpose: :blob_token", source)
        self.assertIn(
            "ActiveStorage::Service::S3Service.prepend(InfinitoSameOriginStorage::DirectUpload)",
            source,
        )

    def test_boot_guard_pins_the_patched_signatures(self):
        self.assertEqual(
            _initializer_signatures(),
            {**ACTIVESTORAGE_7_2_2_2, **DECIDIM_0_31_6},
            "the boot guard must expect exactly the activestorage 7.2.2.2 and "
            "decidim 0.31.6 signatures the patch was written against",
        )

    def test_rich_text_blobs_render_through_the_app_route(self):
        source = read_text(str(INITIALIZER))

        self.assertRegex(
            source,
            r"(?ms)^  module LocalBlobUrl\n    protected\n\n    def blob_url\(blob, variation = nil\)\n      local_blob_url\(blob, variation\)\n    end\n  end$",
        )
        self.assertIn(
            "Decidim::ContentRenderers::BlobRenderer.prepend(InfinitoSameOriginStorage::LocalBlobUrl)",
            source,
        )

    def test_redirect_routes_serve_through_the_proxy(self):
        self.assertEqual(_prepended_routes(), PREPENDED_ROUTES)

    def test_each_path_shape_takes_the_route_of_its_own_shape(self):
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

    def test_storage_reads_skip_the_request_throttle(self):
        source = read_text(str(INITIALIZER))

        self.assertIn('require "rack/attack"', source)
        self.assertIn(
            'Rack::Attack.safelist("same-origin storage reads") { |request| '
            "InfinitoSameOriginStorage.storage_read?(request) }",
            source,
        )
        self.assertRegex(
            source,
            r'\(request\.get\? \|\| request\.head\?\) &&\n\s+request\.path\.start_with\?\("#\{ActiveStorage\.routes_prefix\}/blobs/", "#\{ActiveStorage\.routes_prefix\}/representations/"\)',
        )

    def test_boot_guard_runs_before_the_patch(self):
        source = read_text(str(INITIALIZER))

        self.assertLess(
            source.index("SIGNATURES.each"),
            source.index("S3Service.prepend"),
            "after the prepend instance_method answers with the patch's own parameters",
        )

    def test_decidim_version_is_the_verified_one(self):
        self.assertEqual(
            SERVICES["decidim"]["version"],
            VERIFIED_DECIDIM,
            "re-verify the initializer's SIGNATURES and Decidim::AssetRouter::Storage "
            "against the activestorage and decidim-core this image ships, then "
            "move VERIFIED_DECIDIM",
        )

    def test_the_image_installs_the_initializer(self):
        self.assertIn(
            "COPY ${DECIDIM_PATCH_RUBY_HOST_REL}/initializers/ /code/config/initializers/",
            read_text(str(ROLE / "files" / "Dockerfile")),
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
