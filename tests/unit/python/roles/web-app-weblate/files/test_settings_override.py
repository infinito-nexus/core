from __future__ import annotations

import unittest
from pathlib import PurePosixPath

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_VOLUMES

from ._stand_ins import (
    MIDDLEWARE_MODULE_PATH,
    STRATEGY_MODULE_PATH,
    UPSTREAM_MIDDLEWARE,
    UPSTREAM_PROXY,
    apply_override,
    upstream_settings,
)

ROLE = PROJECT_ROOT / "roles/web-app-weblate"
UPSTREAM_LOADER_TARGET = "/app/data/settings-override.py"
SETTINGS_SERVICES = ["beat", "weblate", "worker"]


def config_entry(key: str) -> dict:
    return load_yaml_str(read_text(str(ROLE / ROLE_FILE_META_VOLUMES)))[key]


class TestSettingsOverride(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = apply_override(upstream_settings())

    def test_the_proxy_middleware_is_replaced_in_place(self) -> None:
        middleware = self.settings["MIDDLEWARE"]
        replacement = middleware[UPSTREAM_MIDDLEWARE.index(UPSTREAM_PROXY)]
        self.assertNotIn(UPSTREAM_PROXY, middleware)
        self.assertEqual(
            replacement, "weblate_network.middleware.NetworkProxyMiddleware"
        )
        self.assertEqual(
            [entry for entry in middleware if entry != replacement],
            [entry for entry in UPSTREAM_MIDDLEWARE if entry != UPSTREAM_PROXY],
        )

    def test_social_auth_builds_urls_from_the_request(self) -> None:
        self.assertEqual(
            self.settings["SOCIAL_AUTH_STRATEGY"],
            "weblate_network.strategy.NetworkStrategy",
        )
        self.assertIs(
            self.settings["SOCIAL_AUTH_REDIRECT_IS_HTTPS"],
            False,
            "social_core rewrites http:// to https:// in every redirect_uri while "
            "this is on, so the onion callback would leave the onion vhost",
        )

    def test_weblate_leaves_the_http_redirect_to_the_proxy(self) -> None:
        self.assertIs(self.settings["SECURE_SSL_REDIRECT"], False)

    def test_the_language_cookie_survives_the_onion_vhost(self) -> None:
        self.assertEqual(
            self.settings["LANGUAGE_COOKIE_SAMESITE"],
            "Lax",
            "the onion vhost strips Secure and browsers drop SameSite=None without it",
        )

    def test_each_referenced_module_is_mounted_on_sys_path(self) -> None:
        for key, source, dotted in (
            (
                "network_strategy",
                STRATEGY_MODULE_PATH,
                self.settings["SOCIAL_AUTH_STRATEGY"],
            ),
            (
                "network_middleware",
                MIDDLEWARE_MODULE_PATH,
                self.settings["MIDDLEWARE"][UPSTREAM_MIDDLEWARE.index(UPSTREAM_PROXY)],
            ),
        ):
            with self.subTest(entry=key):
                mounted = {
                    PurePosixPath(mount["target"])
                    for mount in config_entry(key)["mounts"]
                }
                self.assertEqual(len(mounted), 1)
                target = mounted.pop()
                self.assertEqual(target.name, source.name)
                module = target.relative_to(
                    self.settings["_infinito_origin_dir"]
                ).with_suffix("")
                self.assertEqual(".".join(module.parts), dotted.rsplit(".", 1)[0])

    def test_a_renamed_upstream_middleware_fails_loudly(self) -> None:
        settings = upstream_settings()
        settings["MIDDLEWARE"].remove(UPSTREAM_PROXY)
        with self.assertRaises(RuntimeError):
            apply_override(settings)

    def test_a_renamed_upstream_strategy_fails_loudly(self) -> None:
        settings = upstream_settings()
        settings["SOCIAL_AUTH_STRATEGY"] = "weblate.accounts.strategy.Other"
        with self.assertRaises(RuntimeError):
            apply_override(settings)


class TestOverrideMounts(unittest.TestCase):
    def test_every_settings_reader_gets_every_file_read_only(self) -> None:
        for key, target in (
            ("settings_override", UPSTREAM_LOADER_TARGET),
            ("network_strategy", None),
            ("network_middleware", None),
        ):
            with self.subTest(entry=key):
                entry = config_entry(key)
                self.assertEqual(entry["type"], "config")
                self.assertEqual(entry["mode"], "0444")
                self.assertEqual(
                    sorted(mount["service"] for mount in entry["mounts"]),
                    SETTINGS_SERVICES,
                    "web, beat and worker all load settings_docker.py, so each "
                    "needs the override and the module it names",
                )
                if target:
                    self.assertEqual(
                        {mount["target"] for mount in entry["mounts"]}, {target}
                    )


if __name__ == "__main__":
    unittest.main()
