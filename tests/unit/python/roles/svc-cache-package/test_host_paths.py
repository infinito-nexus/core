from __future__ import annotations

import importlib
import unittest
from unittest import mock

from ansible.errors import AnsibleError

from plugins.lookup.container_ports import LookupModule as ContainerPorts
from utils.cache.yaml import load_yaml_str

render = importlib.import_module("tests.unit.python.roles.svc-cache-package._render")

DIR_CACHE = "/var/cache/infinito/core/cache"
DATA = f"{DIR_CACHE}/package/data"
CA = f"{DIR_CACHE}/package/frontend/ca"
CERTS = f"{DIR_CACHE}/package/frontend/certs"
NEXUS_DATA = "/nexus-data"
INFRA = {
    "package": {"data_path": DATA},
    "frontend": {
        "ca_path": CA,
        "certs_path": CERTS,
        "ports": {"local": {"http": 80, "https": 443}},
    },
}
PORTS_LINE = "container_ports: "


def _volumes(service: str, override=None) -> list:
    return load_yaml_str(render.mounts(service, override))["volumes"]


def _frontend_terms(override=None) -> list:
    return render.role_var(render.environment(override), "CACHE_PACKAGE_FRONTEND_PORTS")


def _published(override) -> str:
    with mock.patch("plugins.lookup.container_ports.lookup_loader") as loader:
        loader.get.return_value.run.return_value = [render.applications(override)]
        return ContainerPorts().run(
            [["frontend", "http"], ["frontend", "https"]],
            variables={
                "application_id": render.APPLICATION_ID,
                "DEPLOYMENT_MODE": "compose",
            },
        )[0]


def _frontend_ports(compose: str) -> list:
    block = load_yaml_str(compose)["services"]["frontend"]
    return block["container_ports"][0] if "container_ports" in block else []


class TestWithoutTheKeys(unittest.TestCase):
    def test_every_render_is_byte_identical_to_today(self) -> None:
        self.assertEqual(render.renders(), render.fixture())

    def test_the_infra_keys_break_the_identity(self) -> None:
        rendered = render.renders(INFRA)
        today = render.fixture()
        for key in (
            "compose",
            "certs_env",
            "mounts_package",
            "mounts_bootstrap",
            "mounts_frontend",
        ):
            with self.subTest(render=key):
                self.assertNotEqual(rendered[key], today[key])

    def test_the_role_publishes_no_frontend_port(self) -> None:
        self.assertEqual(_frontend_terms(), [])
        self.assertEqual(_frontend_ports(render.compose()), [])


class TestDataPath(unittest.TestCase):
    def test_nexus_and_bootstrap_bind_the_data_path(self) -> None:
        for service in ("package", "bootstrap"):
            with self.subTest(service=service):
                self.assertIn(f"{DATA}:{NEXUS_DATA}", _volumes(service, INFRA))
                self.assertNotIn(f"data:{NEXUS_DATA}", _volumes(service, INFRA))

    def test_without_the_key_both_keep_the_named_volume(self) -> None:
        for service in ("package", "bootstrap"):
            with self.subTest(service=service):
                self.assertIn(f"data:{NEXUS_DATA}", _volumes(service))
                self.assertNotIn(f"{DATA}:{NEXUS_DATA}", _volumes(service))


class TestFrontendPaths(unittest.TestCase):
    def test_the_frontend_mounts_the_configured_ca_and_certs(self) -> None:
        volumes = _volumes("frontend", INFRA)
        self.assertIn(f"{CA}:/etc/nginx/ca:ro", volumes)
        self.assertIn(f"{CERTS}:/etc/nginx/certs:ro", volumes)

    def test_the_issuer_writes_into_the_configured_directories(self) -> None:
        env = load_yaml_str(render.certs_env(INFRA))
        self.assertEqual(env["INFINITO_CACHE_PACKAGE_FRONTEND_CA_DIR"], CA)
        self.assertEqual(env["INFINITO_CACHE_PACKAGE_FRONTEND_CERTS_DIR"], CERTS)

    def test_without_the_keys_neither_lands_on_the_cache_base(self) -> None:
        env = load_yaml_str(render.certs_env())
        self.assertNotIn(DIR_CACHE, render.mounts("frontend"))
        self.assertNotIn(DIR_CACHE, env["INFINITO_CACHE_PACKAGE_FRONTEND_CA_DIR"])
        self.assertNotIn(DIR_CACHE, env["INFINITO_CACHE_PACKAGE_FRONTEND_CERTS_DIR"])


class TestFrontendPorts(unittest.TestCase):
    def test_the_declared_local_ports_reach_the_frontend(self) -> None:
        expected = [["frontend", "http"], ["frontend", "https"]]
        self.assertEqual(sorted(map(list, _frontend_terms(INFRA))), expected)
        self.assertEqual(sorted(_frontend_ports(render.compose(INFRA))), expected)

    def test_the_frontend_publishes_80_and_443(self) -> None:
        self.assertEqual(
            _published(INFRA).splitlines(),
            ["ports:", '  - "80:80"', '  - "443:443"'],
        )

    def test_without_local_ports_the_frontend_has_nothing_to_publish(self) -> None:
        with self.assertRaises(AnsibleError):
            _published(None)


if __name__ == "__main__":
    unittest.main()
