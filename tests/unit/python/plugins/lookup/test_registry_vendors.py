from __future__ import annotations

import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError

from plugins.lookup.registry_vendors import (
    CACHE_ROLE,
    LookupModule,
    registry_of,
    route_reference,
    unrouted,
)

FRONT = "192.168.205.1:5002"
VENDORS = {"front": FRONT, "registries": ["ghcr.io", "quay.io"]}
CONFIG = {
    (CACHE_ROLE, "services.cache.flavor"): "registry",
    (CACHE_ROLE, "networks.local.subnet"): "192.168.205.0/24",
    (CACHE_ROLE, "services.front.ports.local.registry"): 5002,
}
MULTI_PROXY = {**CONFIG, (CACHE_ROLE, "services.cache.flavor"): "multi-proxy"}
UNLISTED = [
    "nginx:1.31-alpine",
    "library/nginx:1.31-alpine",
    "docker.io/library/nginx:1.31-alpine",
    "registry-1.docker.io/library/nginx:1.31-alpine",
    "mcr.microsoft.com/playwright:v1.60.0",
    "localhost:5000/app:1",
    "ghcr.io.example.com/foo/bar:1",
    "example.com/ghcr.io/foo:1",
    "nextcloud_custom:34",
    "",
]


def _vendors(variables, registries=("ghcr.io", "quay.io"), config=None):
    config_mock = mock.MagicMock()
    config_mock.run.side_effect = lambda terms, **_k: [(config or CONFIG)[tuple(terms)]]
    with (
        mock.patch("plugins.lookup.registry_vendors.lookup_loader") as loader,
        mock.patch(
            "plugins.lookup.registry_vendors.image_registries",
            return_value=list(registries),
        ),
    ):
        loader.get.return_value = config_mock
        module = LookupModule()
        module._loader = mock.MagicMock()
        return module.run([], variables=variables)[0], config_mock


def _cache_host(**extra):
    return {"group_names": [CACHE_ROLE], "DEPLOYMENT_MODE": "compose", **extra}


class TestRouteReference(unittest.TestCase):
    def test_a_listed_registry_is_routed_through_the_front(self):
        self.assertEqual(
            route_reference("ghcr.io/foo/bar:1.0", VENDORS),
            f"{FRONT}/ghcr.io/foo/bar:1.0",
        )

    def test_a_digest_pin_keeps_its_digest(self):
        self.assertEqual(
            route_reference("quay.io/foo/bar@sha256:abc", VENDORS),
            f"{FRONT}/quay.io/foo/bar@sha256:abc",
        )

    def test_a_reference_whose_registry_is_not_listed_is_never_prefixed(self):
        for reference in UNLISTED:
            with self.subTest(reference=reference):
                self.assertEqual(route_reference(reference, VENDORS), reference)

    def test_no_front_routes_nothing(self):
        for vendors in (None, {}, unrouted(), {"front": "", "registries": ["ghcr.io"]}):
            with self.subTest(vendors=vendors):
                self.assertEqual(
                    route_reference("ghcr.io/foo/bar:1.0", vendors),
                    "ghcr.io/foo/bar:1.0",
                )

    def test_no_registry_routes_nothing(self):
        self.assertEqual(
            route_reference("ghcr.io/foo/bar:1.0", {"front": FRONT, "registries": []}),
            "ghcr.io/foo/bar:1.0",
        )

    def test_the_registry_of_a_reference(self):
        cases = {
            "ghcr.io/foo/bar:1.0": "ghcr.io",
            "ghcr.io/foo/bar@sha256:abc": "ghcr.io",
            "ghcr.io/foo/bar:1.0@sha256:abc": "ghcr.io",
            "registry.example.com:5000/foo:1": "registry.example.com:5000",
            "nginx:1.31": None,
            "library/nginx": None,
            "Not A Reference": None,
        }
        for reference, registry in cases.items():
            with self.subTest(reference=reference):
                self.assertEqual(registry_of(reference), registry)


class TestRegistryVendorsLookup(unittest.TestCase):
    def test_the_cache_host_in_compose_gets_the_front_on_its_gateway(self):
        vendors, _ = _vendors(_cache_host())
        self.assertEqual(
            vendors, {"front": FRONT, "registries": ["ghcr.io", "quay.io"]}
        )

    def test_a_host_outside_the_cache_group_routes_nothing(self):
        vendors, config = _vendors({"group_names": ["web-app-nextcloud"]})
        self.assertEqual(vendors, unrouted())
        config.run.assert_not_called()

    def test_a_swarm_deploy_routes_nothing(self):
        for extra in (
            {"DEPLOYMENT_MODE": "swarm"},
            {"compose_mode_force": "swarm"},
            {"DEPLOYMENT_MODE": "swarm", "compose_mode_force": "compose"},
        ):
            with self.subTest(extra=extra):
                vendors, config = _vendors(_cache_host(**extra))
                self.assertEqual(vendors, unrouted())
                config.run.assert_not_called()

    def test_a_registry_no_path_component_can_name_is_left_upstream(self):
        vendors, _ = _vendors(
            _cache_host(),
            registries=("ghcr.io", "localhost", "registry.example.com:5000"),
        )
        self.assertEqual(vendors["registries"], ["ghcr.io"])

    def test_without_a_vendor_image_nothing_is_routed(self):
        vendors, config = _vendors(_cache_host(), registries=())
        self.assertEqual(vendors, unrouted())
        config.run.assert_not_called()

    def test_terms_come_back_routed_for_the_host(self):
        with (
            mock.patch("plugins.lookup.registry_vendors.lookup_loader") as loader,
            mock.patch(
                "plugins.lookup.registry_vendors.image_registries",
                return_value=["ghcr.io"],
            ),
        ):
            loader.get.return_value.run.side_effect = lambda terms, **_k: [
                CONFIG[tuple(terms)]
            ]
            module = LookupModule()
            module._loader = mock.MagicMock()
            routed = module.run(
                ["ghcr.io/foo/bar:1.0", "nginx:1.31"], variables=_cache_host()
            )
        self.assertEqual(routed, [f"{FRONT}/ghcr.io/foo/bar:1.0", "nginx:1.31"])

    def test_terms_come_back_unchanged_off_the_cache_host(self):
        module = LookupModule()
        module._loader = mock.MagicMock()
        self.assertEqual(
            module.run(["ghcr.io/foo/bar:1.0"], variables={"group_names": []}),
            ["ghcr.io/foo/bar:1.0"],
        )

    def test_the_multi_proxy_flavor_routes_nothing(self):
        vendors, config = _vendors(_cache_host(), config=MULTI_PROXY)
        self.assertEqual(vendors, unrouted())
        self.assertEqual(
            [call.args[0] for call in config.run.call_args_list],
            [[CACHE_ROLE, "services.cache.flavor"]],
        )

    def test_the_registry_flavor_routes_through_the_front(self):
        vendors, _ = _vendors(_cache_host(), config=CONFIG)
        self.assertEqual(vendors["front"], FRONT)

    def test_terms_come_back_unchanged_under_the_multi_proxy_flavor(self):
        with (
            mock.patch("plugins.lookup.registry_vendors.lookup_loader") as loader,
            mock.patch(
                "plugins.lookup.registry_vendors.image_registries",
                return_value=["ghcr.io"],
            ),
        ):
            loader.get.return_value.run.side_effect = lambda terms, **_k: [
                MULTI_PROXY[tuple(terms)]
            ]
            module = LookupModule()
            module._loader = mock.MagicMock()
            routed = module.run(["ghcr.io/foo/bar:1.0"], variables=_cache_host())
        self.assertEqual(routed, ["ghcr.io/foo/bar:1.0"])

    def test_a_subnet_without_a_gateway_fails_the_render(self):
        config = {**CONFIG, (CACHE_ROLE, "networks.local.subnet"): "192.168.205.1/24"}
        with self.assertRaises(AnsibleError):
            _vendors(_cache_host(), config=config)


if __name__ == "__main__":
    unittest.main()
