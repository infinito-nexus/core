from __future__ import annotations

import importlib
import json
import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str

render = importlib.import_module("tests.unit.python.roles.svc-registry-cache._render")

REGISTRIES = ["gcr.io", "ghcr.io", "quay.io", "registry.k8s.io"]
CAP = "40g"
IDLE_DAYS = 14
CASES = {
    "compose": ("compose.yml.j2", []),
    "compose_vendors": ("compose.yml.j2", render.VENDORS),
    "env": ("env.j2", []),
    "front": ("front.conf.j2", render.VENDORS),
}
PROBES = {
    "registry": (
        {"flavor": "wget", "port_key": "registry", "path": "v2/"},
        "http://127.0.0.1:5000/v2/",
    ),
    "multi-proxy": (
        {"flavor": "http", "port_key": "proxy", "path": "ca.crt"},
        "http://127.0.0.1:3128/ca.crt",
    ),
}
FLAVOR_LOOKUP = "lookup('config', 'svc-registry-cache', 'services.cache.flavor')"
STRINGIFIED = (
    "{{ lookup('config', 'svc-registry-cache', 'services.cache.healthchecks')"
    f"[{FLAVOR_LOOKUP}] | string }}}}"
)


def _renders(flavor: str) -> dict[str, str]:
    return {
        key: render.render(name, flavor, vendors)
        for key, (name, vendors) in CASES.items()
    }


def _multi_proxy(registries=REGISTRIES, cap=CAP, idle=IDLE_DAYS) -> dict[str, str]:
    return {
        "compose": render.render(
            "compose.yml.j2",
            "multi-proxy",
            multi_proxy={"registries": registries, "max_size": cap},
        ),
        "env": render.render(
            "env.j2",
            "multi-proxy",
            multi_proxy={
                "registries": registries,
                "max_size": cap,
                "max_idle_days": idle,
            },
        ),
    }


def _serves(env: str, registries: list[str]) -> bool:
    return set(registries) <= set(render.env_values(env)["REGISTRIES"].split(","))


def _stub_args(value):
    return json.loads(value) if isinstance(value, str) else value


class TestRegistryFlavor(unittest.TestCase):
    def test_the_role_defaults_to_the_registry_flavor(self) -> None:
        self.assertEqual(render.cache_defaults()["flavor"], "registry")

    def test_every_render_is_byte_identical_to_today(self) -> None:
        self.assertEqual(_renders("registry"), render.fixture())

    def test_an_inventory_without_the_key_renders_today(self) -> None:
        self.assertEqual(_renders(render.flavor_of({})), render.fixture())

    def test_a_changed_template_breaks_the_identity(self) -> None:
        source = read_text(str(render.TEMPLATES / "compose.yml.j2")).replace(
            "['cache', 'registry']", "['cache', 'proxy']", 1
        )
        changed = render.render("compose.yml.j2", "registry", template=source)
        self.assertNotEqual(changed, render.fixture()["compose"])

    def test_the_multi_proxy_flavor_differs_from_today(self) -> None:
        self.assertNotEqual(_renders("multi-proxy"), render.fixture())


class TestMultiProxyFlavor(unittest.TestCase):
    def test_the_env_serves_every_registry_with_the_cap_and_window(self) -> None:
        env = render.env_values(_multi_proxy()["env"])
        self.assertTrue(_serves(_multi_proxy()["env"], REGISTRIES))
        self.assertEqual(env["CACHE_MAX_SIZE"], CAP)
        self.assertEqual(env["CACHE_MAX_IDLE_DAYS"], str(IDLE_DAYS))
        self.assertEqual(env["ENABLE_MANIFEST_CACHE"], "true")
        self.assertEqual(env["MANIFEST_CACHE_SECONDARY_TIME"], "24h")
        self.assertEqual(env["DISABLE_IPV6"], "true")
        self.assertNotIn("REGISTRY_PROXY_REMOTEURL", env)

    def test_a_missing_registry_is_detected(self) -> None:
        env = _multi_proxy(registries=REGISTRIES[1:])["env"]
        self.assertFalse(_serves(env, REGISTRIES))

    def test_the_cap_and_window_follow_the_config(self) -> None:
        env = render.env_values(_multi_proxy(cap="12g", idle=7)["env"])
        self.assertEqual(
            [env["CACHE_MAX_SIZE"], env["CACHE_MAX_IDLE_DAYS"]], ["12g", "7"]
        )

    def test_the_proxy_runs_the_pinned_image_on_its_port(self) -> None:
        services = load_yaml_str(_multi_proxy()["compose"])["services"]
        self.assertEqual(set(services), {"cache"})
        cache = services["cache"]
        proxy = render.cache_defaults()["multi_proxy"]
        self.assertEqual(
            _stub_args(cache["container_image"]),
            [
                ["svc-registry-cache", "cache"],
                {"image": proxy["image"], "version": proxy["version"]},
            ],
        )
        self.assertEqual(
            _stub_args(cache["container_ports"]), [[["cache", "proxy"]], {}]
        )
        self.assertEqual(
            cache["entrypoint"], [render.ENTRYPOINT_TARGET, "/entrypoint.sh"]
        )
        ports = render.cache_defaults()["ports"]
        self.assertEqual(
            [ports["local"]["proxy"], ports["internal"]["proxy"]], [3128, 3128]
        )

    def test_the_proxy_serves_no_vendor_front(self) -> None:
        expression = render._VENDOR._environment().compile_expression(
            render.role_var("REGISTRY_CACHE_VENDORS")
        )
        self.assertEqual(expression(REGISTRY_CACHE_FLAVOR="multi-proxy"), [])

    def test_mirror_and_ca_mount_only_in_the_multi_proxy_flavor(self) -> None:
        for key, target in (
            ("multi_proxy_mirror", "/docker_mirror_cache"),
            ("multi_proxy_ca", "/ca"),
            ("multi_proxy_entrypoint", render.ENTRYPOINT_TARGET),
            ("multi_proxy_stale", "/etc/nginx/nginx.manifest.stale.conf"),
        ):
            with self.subTest(volume=key):
                _, mount = render.volume_mount(key)
                self.assertEqual(mount["service"], "cache")
                self.assertEqual(mount["target"], target)
                self.assertIn("== 'multi-proxy'", mount["when"])
        _, data = render.volume_mount("data")
        self.assertIn("== 'registry'", data["when"])


class TestCacheHealthcheck(unittest.TestCase):
    def test_each_flavor_renders_the_probe_it_rendered_before(self) -> None:
        for flavor, (before, url) in PROBES.items():
            with self.subTest(flavor=flavor):
                block = render.healthcheck(flavor)
                self.assertEqual(block, render.healthcheck(flavor, before))
                self.assertIn(url, block)

    def test_a_selection_of_the_other_flavor_is_detected(self) -> None:
        declared = render.cache_defaults()["healthcheck"]
        swapped = f"('multi-proxy' if {FLAVOR_LOOKUP} == 'registry' else 'registry')"
        wrong = declared.replace(FLAVOR_LOOKUP, swapped, 1)
        self.assertNotEqual(wrong, declared)
        for flavor, (before, _url) in PROBES.items():
            with self.subTest(flavor=flavor):
                self.assertNotEqual(
                    render.healthcheck(flavor, wrong),
                    render.healthcheck(flavor, before),
                )


class TestCacheHealthcheckConfigPath(unittest.TestCase):
    def test_the_config_lookup_hands_over_the_flavor_entry_as_a_mapping(self) -> None:
        table = render.cache_defaults()["healthchecks"]
        for flavor in PROBES:
            with self.subTest(flavor=flavor):
                declared = render.config_healthcheck(flavor)
                self.assertIsInstance(declared, dict)
                self.assertEqual(declared, table[flavor])

    def test_negative_control_a_stringified_entry_is_no_mapping(self) -> None:
        table = render.cache_defaults()["healthchecks"]
        for flavor in PROBES:
            with self.subTest(flavor=flavor):
                declared = render.config_healthcheck(flavor, STRINGIFIED)
                self.assertNotIsInstance(declared, dict)
                self.assertNotEqual(declared, table[flavor])


if __name__ == "__main__":
    unittest.main()
