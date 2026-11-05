from __future__ import annotations

import importlib.util
import re
import unittest
import unittest.mock as mock

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.roles.mapping import (
    ROLE_FILE_META_VOLUMES,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

from . import PROJECT_ROOT

APP = "web-app-funkwhale"
ROLE = PROJECT_ROOT / "roles" / APP
PROVIDER_HOST = "api.seaweedfs.s3.example.com"
CLEARNET = "funkwhale.example.com"
ONION = "funkwhale." + "a" * 56 + ".onion"
MODULES = {
    "same_origin_settings": "settings",
    "same_origin_storage": "storage",
    "same_origin_urls": "urls",
}
PYTHON_SERVICES = {"api", "celeryworker", "celerybeat", "migrate"}


def _objstore(served_on: list[str]) -> dict:
    """
    Args:
        served_on: the domains the node serves funkwhale under.

    Returns:
        lookup('objstore', 'web-app-funkwhale') for a shared seaweedfs with a clearnet API domain.
    """
    spec = importlib.util.spec_from_file_location(
        "lookup_objstore_funkwhale", str(PROJECT_ROOT / "plugins/lookup/objstore.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    payloads = {
        "applications": {
            APP: {
                "services": {"seaweedfs": {"enabled": True, "shared": True}},
                "secrets": {"credentials": {"objstore_secret_key": "sk"}},
            },
            "web-svc-seaweedfs": {
                "services": {"seaweedfs": {"name": "seaweedfs"}},
                "domains": {"canonical": {"api": PROVIDER_HOST}},
            },
        },
        "domains": {APP: served_on},
    }
    lookup = module.LookupModule()
    lookup._templar = mock.MagicMock(available_variables={})
    lookup._loader = mock.MagicMock()
    with (
        mock.patch.object(module, "lookup_loader") as loader,
        mock.patch.object(module, "entity_name", return_value="funkwhale"),
    ):
        loader.get.side_effect = lambda name, **_kwargs: mock.MagicMock(
            run=lambda _terms, **_kw: [payloads[name]]
        )
        return lookup.run(
            [APP], variables={"DIR_COMPOSITIONS": "/opt/compose/", "TLS_ENABLED": True}
        )[0]


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
        keep_trailing_newline=True,
    )
    env.filters["bool"] = bool
    env.filters["dotenv_quote"] = lambda value: value
    return env


def _settings_module(objstore_enabled: bool) -> str:
    """
    Args:
        objstore_enabled: whether the object store is bound.

    Returns:
        FUNKWHALE_DJANGO_SETTINGS_MODULE as vars/main.yml renders it.
    """
    expression = load_yaml(str(ROLE / ROLE_FILE_VARS_MAIN))[
        "FUNKWHALE_DJANGO_SETTINGS_MODULE"
    ]
    return (
        _environment()
        .from_string(expression)
        .render(FUNKWHALE_OBJSTORE_ENABLED=objstore_enabled)
    )


def _render_env(domain: str, objstore: dict) -> dict[str, str]:
    """
    Args:
        domain: the canonical domain of funkwhale on the node.
        objstore: the objstore lookup payload.

    Returns:
        The rendered env file of the role as a key to value mapping.
    """
    env = _environment()

    def lookup(name: str, *terms, **_kwargs):
        if name == "objstore":
            return objstore[terms[1]]
        if name == "domain":
            return domain
        if name == "tls":
            return "http" if domain.endswith(".onion") else "https"
        if name == "email":
            return {"enabled": False}
        if name == "config":
            return False if terms[1] == "services.ldap.enabled" else "secret"
        if name in ("database", "engine"):
            return "x"
        raise AssertionError(f"env.j2 renders an unexpected lookup {name}{terms}")

    env.globals["lookup"] = lookup
    rendered = env.get_template(f"roles/{APP}/templates/env.j2").render(
        application_id=APP,
        HOST_TIMEZONE="UTC",
        MODE_DEBUG=False,
        FUNKWHALE_MUSIC_DIR="/var/lib/funkwhale/music",
        FUNKWHALE_MEDIA_DIR="/var/lib/funkwhale/media",
        FUNKWHALE_STATIC_DIR="/var/lib/funkwhale/static",
        FUNKWHALE_DOCKER_API_PORT=5000,
        FUNKWHALE_CELERYD_CONCURRENCY=1,
        FUNKWHALE_DJANGO_SETTINGS_MODULE=_settings_module(objstore["enabled"]),
        POSTGRES_ALLOWED_AVG_CONNECTIONS=10,
    )
    return dict(
        line.split("=", 1)
        for line in rendered.splitlines()
        if "=" in line and not line.startswith("#")
    )


def _render_nginx() -> str:
    """
    Returns:
        The front nginx override as the role renders it.
    """
    return (
        _environment()
        .get_template(f"roles/{APP}/templates/nginx.conf.j2")
        .render(
            NETWORK_DOCKER_DNS_NGINX_DIRECTIVE="resolver 127.0.0.11 valid=30s ipv6=off;"
        )
    )


class TestFunkwhaleSameOriginEnv(unittest.TestCase):
    SCENARIOS = (("clearnet", CLEARNET), ("onion", ONION))

    def test_no_env_value_names_the_provider_host(self):
        for label, domain in self.SCENARIOS:
            with self.subTest(network=label):
                values = _render_env(domain, _objstore([domain]))

                leaks = {k: v for k, v in values.items() if PROVIDER_HOST in v}
                self.assertEqual(leaks, {})

    def test_the_client_signs_for_the_internal_store(self):
        values = _render_env(CLEARNET, _objstore([CLEARNET]))

        self.assertEqual(values["AWS_S3_ENDPOINT_URL"], "http://seaweedfs:8333")
        self.assertNotIn("AWS_CA_BUNDLE", values)

    def test_the_object_store_runs_the_same_origin_settings(self):
        values = _render_env(CLEARNET, _objstore([CLEARNET]))

        self.assertEqual(values["DJANGO_SETTINGS_MODULE"], "same_origin_settings")

    def test_without_the_object_store_the_stock_settings_run(self):
        self.assertEqual(_settings_module(False), "config.settings.production")


class TestFunkwhaleFrontNginx(unittest.TestCase):
    def test_public_media_goes_to_the_api(self):
        block = re.search(
            r"location ~ \^/media/\(attachments\|__sized__\|dynamic_preferences\|portability\)/ \{(.*?)\n    \}",
            _render_nginx(),
            flags=re.DOTALL,
        )

        self.assertIsNotNone(block, "the public media prefixes need a location")
        self.assertIn("proxy_pass   http://funkwhale-api;", block.group(1))

    def test_no_media_location_reads_the_empty_local_root(self):
        self.assertNotIn("alias ${MEDIA_ROOT}", _render_nginx())

    def test_the_internal_fetch_resolves_the_store_through_docker_dns(self):
        block = re.search(
            r"location ~ /_protected/media/\(\.\+\) \{(.*?)\n    \}",
            _render_nginx(),
            flags=re.DOTALL,
        ).group(1)

        self.assertIn("resolver 127.0.0.11", block)


class TestFunkwhaleSameOriginMounts(unittest.TestCase):
    def setUp(self):
        self.volumes = load_yaml(str(ROLE / ROLE_FILE_META_VOLUMES))

    def test_every_python_service_mounts_every_module(self):
        for module in MODULES:
            with self.subTest(module=module):
                entry = self.volumes[module]
                self.assertEqual(entry["type"], "config")
                self.assertTrue(
                    entry["source"].endswith(
                        f"'same_origin', '{MODULES[module]}.py'] | path_join }}}}"
                    )
                )
                self.assertEqual(
                    {(mount["service"], mount["target"]) for mount in entry["mounts"]},
                    {(service, f"/app/{module}.py") for service in PYTHON_SERVICES},
                )

    def test_mounts_follow_the_object_store_binding(self):
        for module in MODULES:
            for mount in self.volumes[module]["mounts"]:
                with self.subTest(module=module, service=mount["service"]):
                    self.assertIn(
                        "lookup('objstore', 'web-app-funkwhale', 'enabled')",
                        mount["when"],
                    )

    def test_every_mounted_module_ships_with_the_role(self):
        for module in MODULES:
            with self.subTest(module=module):
                self.assertTrue(
                    (
                        ROLE
                        / "files"
                        / "python"
                        / "same_origin"
                        / f"{MODULES[module]}.py"
                    ).is_file()
                )

    def test_migrate_renders_its_mounts(self):
        compose = read_text(str(ROLE / ROLE_FILE_TEMPL_COMPOSE))
        migrate = compose.split("{% set service_name = 'migrate' %}", 1)[1]

        self.assertIn("lookup('container_volumes', service_name)", migrate)


if __name__ == "__main__":
    unittest.main()
