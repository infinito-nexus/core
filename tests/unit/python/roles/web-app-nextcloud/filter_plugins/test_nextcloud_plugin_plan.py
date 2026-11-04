from __future__ import annotations

import importlib.util
import sys
import unittest

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT


def _load_module(rel_path: str, name: str):
    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


plan_mod = _load_module(
    "roles/web-app-nextcloud/filter_plugins/nextcloud_plugin_plan.py",
    "nextcloud_plugin_plan",
)
nextcloud_plugin_plan = plan_mod.nextcloud_plugin_plan


def _items(*entries):
    return [{"key": key, "value": value} for key, value in entries]


def _apps(enabled=(), disabled=()):
    return {
        "enabled": dict.fromkeys(enabled, "1.0.0"),
        "disabled": dict.fromkeys(disabled, "1.0.0"),
    }


class TestNextcloudPluginPlan(unittest.TestCase):
    def test_enabled_and_running_plugins_only_get_configured(self):
        plan = nextcloud_plugin_plan(
            _items(("calendar", {"enabled": True}), ("deck", {"enabled": True})),
            _apps(enabled=("calendar", "deck")),
        )
        self.assertEqual(
            plan,
            {
                "disable": [],
                "install": [],
                "background": [],
                "enable": [],
                "configure": ["calendar", "deck"],
            },
        )

    def test_missing_plugin_is_installed(self):
        plan = nextcloud_plugin_plan(_items(("deck", {"enabled": True})), _apps())
        self.assertEqual(plan["install"], ["deck"])
        self.assertEqual(plan["configure"], [])

    def test_installed_but_disabled_plugin_is_enabled(self):
        plan = nextcloud_plugin_plan(
            _items(("recognize", {"enabled": True})), _apps(disabled=("recognize",))
        )
        self.assertEqual(plan["enable"], ["recognize"])
        self.assertEqual(plan["install"], [])

    def test_pinned_archive_always_goes_through_install(self):
        plan = nextcloud_plugin_plan(
            _items(
                (
                    "onlyoffice",
                    {"enabled": True, "config": {"archive": "https://x/o.tar.gz"}},
                )
            ),
            _apps(enabled=("onlyoffice",)),
        )
        self.assertEqual(plan["install"], ["onlyoffice"])
        self.assertEqual(plan["configure"], [])

    def test_disabled_plugin_is_disabled_only_while_it_runs(self):
        running = nextcloud_plugin_plan(
            _items(("news", {"enabled": False})), _apps(enabled=("news",))
        )
        idle = nextcloud_plugin_plan(
            _items(("news", {"enabled": False})), _apps(disabled=("news",))
        )
        self.assertEqual(running["disable"], ["news"])
        self.assertEqual(idle["disable"], [])

    def test_later_entry_wins_like_the_per_plugin_loop(self):
        items = _items(
            ("fileslibreofficeedit", {"enabled": True}),
            (
                "onlyoffice",
                {
                    "enabled": True,
                    "config": {
                        "incompatible_plugins": [
                            "richdocuments",
                            "fileslibreofficeedit",
                        ]
                    },
                },
            ),
            ("richdocuments", {"enabled": True}),
        )
        plan = nextcloud_plugin_plan(
            items,
            _apps(enabled=("fileslibreofficeedit", "onlyoffice", "richdocuments")),
        )
        self.assertEqual(plan["disable"], ["fileslibreofficeedit"])
        self.assertEqual(plan["configure"], ["onlyoffice", "richdocuments"])
        self.assertEqual(plan["install"], [])

    def test_incompatible_plugin_outside_the_addons_is_disabled(self):
        plan = nextcloud_plugin_plan(
            _items(
                (
                    "oidc_login",
                    {
                        "enabled": True,
                        "config": {
                            "incompatible_plugins": ["user_oidc", "sociallogin"]
                        },
                    },
                ),
            ),
            _apps(enabled=("oidc_login", "user_oidc")),
        )
        self.assertEqual(plan["disable"], ["user_oidc"])
        self.assertEqual(plan["configure"], ["oidc_login"])

    def test_string_flags_from_templated_config(self):
        plan = nextcloud_plugin_plan(
            _items(("deck", {"enabled": "True"}), ("news", {"enabled": "False"})),
            _apps(enabled=("deck", "news")),
        )
        self.assertEqual(plan["configure"], ["deck"])
        self.assertEqual(plan["disable"], ["news"])

    def test_empty_app_list_installs_every_wanted_plugin(self):
        plan = nextcloud_plugin_plan(_items(("deck", {"enabled": True})), {})
        self.assertEqual(plan["install"], ["deck"])


BACKGROUND = {"enabled": True, "config": {"background_install": True}}


class TestBackgroundPlan(unittest.TestCase):
    def test_a_missing_plugin_marked_background_leaves_the_install_loop(self):
        plan = nextcloud_plugin_plan(
            _items(("deck", {"enabled": True}), ("recognize", BACKGROUND)), _apps()
        )
        self.assertEqual(plan["background"], ["recognize"])
        self.assertEqual(plan["install"], ["deck"])

    def test_an_unmarked_plugin_stays_in_the_install_loop(self):
        plan = nextcloud_plugin_plan(_items(("recognize", {"enabled": True})), _apps())
        self.assertEqual(plan["background"], [])
        self.assertEqual(plan["install"], ["recognize"])

    def test_a_marked_plugin_on_disk_is_enabled_not_reinstalled(self):
        plan = nextcloud_plugin_plan(
            _items(("recognize", BACKGROUND)), _apps(disabled=("recognize",))
        )
        self.assertEqual(plan["background"], [])
        self.assertEqual(plan["enable"], ["recognize"])

    def test_a_marked_running_plugin_is_only_configured(self):
        plan = nextcloud_plugin_plan(
            _items(("recognize", BACKGROUND)), _apps(enabled=("recognize",))
        )
        self.assertEqual(plan["background"], [])
        self.assertEqual(plan["configure"], ["recognize"])

    def test_a_marked_plugin_switched_off_is_not_installed(self):
        plan = nextcloud_plugin_plan(
            _items(
                (
                    "recognize",
                    {"enabled": False, "config": {"background_install": True}},
                )
            ),
            _apps(),
        )
        self.assertEqual(plan["background"], [])
        self.assertEqual(plan["install"], [])

    def test_a_pinned_archive_never_runs_in_the_background(self):
        plan = nextcloud_plugin_plan(
            _items(
                (
                    "onlyoffice",
                    {
                        "enabled": True,
                        "config": {
                            "archive": "https://x/o.tar.gz",
                            "background_install": True,
                        },
                    },
                )
            ),
            _apps(),
        )
        self.assertEqual(plan["background"], [])
        self.assertEqual(plan["install"], ["onlyoffice"])

    def test_a_mandatory_plugin_keeps_its_install_guard(self):
        plan = nextcloud_plugin_plan(
            _items(
                (
                    "oidc_login",
                    {
                        "enabled": True,
                        "config": {"background_install": True, "mandatory": True},
                    },
                )
            ),
            _apps(),
        )
        self.assertEqual(plan["background"], [])
        self.assertEqual(plan["install"], ["oidc_login"])

    def test_a_templated_string_flag_is_honoured(self):
        plan = nextcloud_plugin_plan(
            _items(
                (
                    "recognize",
                    {"enabled": "True", "config": {"background_install": "True"}},
                )
            ),
            _apps(),
        )
        self.assertEqual(plan["background"], ["recognize"])

    def test_every_wanted_plugin_lands_in_exactly_one_list(self):
        items = _items(
            ("deck", {"enabled": True}),
            ("recognize", BACKGROUND),
            ("news", {"enabled": True}),
            ("calendar", {"enabled": True}),
        )
        plan = nextcloud_plugin_plan(
            items, _apps(enabled=("calendar",), disabled=("news",))
        )
        placed = (
            plan["install"] + plan["background"] + plan["enable"] + plan["configure"]
        )
        self.assertCountEqual(placed, ["deck", "recognize", "news", "calendar"])


class TestRecognizeAddon(unittest.TestCase):
    def test_recognize_is_installed_in_the_background(self):
        spec = load_yaml_any(
            str(PROJECT_ROOT / "roles/web-app-nextcloud/meta/addons/recognize.yml")
        )
        plan = nextcloud_plugin_plan(_items(("recognize", spec)), _apps())
        self.assertEqual(plan["background"], ["recognize"])


if __name__ == "__main__":
    unittest.main()
