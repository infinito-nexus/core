from __future__ import annotations

import os
import unittest
import unittest.mock as mock
from pathlib import PurePosixPath

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_VOLUMES

from .weblate_network._stand_ins import (
    ASSOCIATE_BY_EMAIL,
    MIDDLEWARE_MODULE_PATH,
    STRATEGY_MODULE_PATH,
    UPSTREAM_APPS,
    UPSTREAM_MIDDLEWARE,
    UPSTREAM_PIPELINE,
    UPSTREAM_PIPELINE_SOURCE,
    UPSTREAM_PROXY,
    apply_override,
    upstream_settings,
)

ROLE = PROJECT_ROOT / "roles/web-app-weblate"
UPSTREAM_LOADER_TARGET = "/app/data/settings-override.py"
SETTINGS_SERVICES = ["beat", "weblate", "worker"]


def config_entry(key: str) -> dict:
    return load_yaml_str(read_text(str(ROLE / ROLE_FILE_META_VOLUMES)))[key]


def run_override(pipeline: list[str]) -> dict:
    return apply_override({**upstream_settings(), "SOCIAL_AUTH_PIPELINE": pipeline})


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

    def test_the_two_factor_app_is_installed_from_its_mount(self) -> None:
        self.assertEqual(
            self.settings["INSTALLED_APPS"], [*UPSTREAM_APPS, "weblate_infinito"]
        )
        self.assertEqual(
            {mount["target"] for mount in config_entry("two_factor_tasks")["mounts"]},
            {f"{self.settings['_infinito_origin_dir']}/weblate_infinito/tasks.py"},
            "Celery autodiscovers <app>.tasks, so the periodic job lives there",
        )

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

    def test_it_binds_no_setting_upstream_does_not_define(self) -> None:
        self.assertEqual(
            {name for name in self.settings if name.isupper()},
            {name for name in upstream_settings() if name.isupper()},
        )


class TestSubjectLinkingWithoutSso(unittest.TestCase):
    @mock.patch.dict(os.environ, {}, clear=True)
    def test_the_pipeline_keeps_associate_by_email_without_sso(self) -> None:
        self.assertEqual(
            run_override(list(UPSTREAM_PIPELINE))["SOCIAL_AUTH_PIPELINE"],
            list(UPSTREAM_PIPELINE),
        )


class TestSubjectLinking(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.dict(
            os.environ, {"WEBLATE_SOCIAL_AUTH_OIDC_KEY": "weblate"}
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_associate_by_email_leaves_the_pipeline(self) -> None:
        self.assertNotIn(
            ASSOCIATE_BY_EMAIL,
            run_override(list(UPSTREAM_PIPELINE))["SOCIAL_AUTH_PIPELINE"],
        )

    def test_every_other_step_keeps_its_upstream_order(self) -> None:
        self.assertEqual(
            run_override(list(UPSTREAM_PIPELINE))["SOCIAL_AUTH_PIPELINE"],
            [step for step in UPSTREAM_PIPELINE if step != ASSOCIATE_BY_EMAIL],
            UPSTREAM_PIPELINE_SOURCE,
        )

    def test_a_step_upstream_inserted_before_the_override_survives(self) -> None:
        pipeline = list(UPSTREAM_PIPELINE)
        pipeline.insert(
            pipeline.index("weblate.accounts.pipeline.second_factor") + 1,
            "weblate.legal.pipeline.tos_confirm",
        )
        result = run_override(pipeline)["SOCIAL_AUTH_PIPELINE"]
        self.assertIn("weblate.legal.pipeline.tos_confirm", result)
        self.assertEqual(
            result, [step for step in pipeline if step != ASSOCIATE_BY_EMAIL]
        )

    def test_the_subject_lookup_still_precedes_account_creation(self) -> None:
        result = run_override(list(UPSTREAM_PIPELINE))["SOCIAL_AUTH_PIPELINE"]
        self.assertLess(
            result.index("social_core.pipeline.social_auth.social_user"),
            result.index("social_core.pipeline.user.create_user"),
        )


class TestOverrideMounts(unittest.TestCase):
    def test_every_settings_reader_gets_every_file_read_only(self) -> None:
        for key, target in (
            ("settings_override", UPSTREAM_LOADER_TARGET),
            ("network_strategy", None),
            ("network_middleware", None),
            ("two_factor_tasks", None),
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

    def test_one_entry_alone_mounts_the_file_upstream_execs(self) -> None:
        volumes = load_yaml_str(read_text(str(ROLE / ROLE_FILE_META_VOLUMES)))
        self.assertEqual(
            [
                key
                for key, entry in volumes.items()
                if any(
                    mount["target"] == UPSTREAM_LOADER_TARGET
                    for mount in entry["mounts"]
                )
            ],
            ["settings_override"],
        )


if __name__ == "__main__":
    unittest.main()
