from __future__ import annotations

import importlib.util
import sys
import unittest

from ansible.template import Templar, trust_as_template

from . import PROJECT_ROOT


def _load_module(rel_path: str, name: str):
    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


config_mod = _load_module(
    "roles/web-app-nextcloud/filter_plugins/nextcloud_plugin_config.py",
    "nextcloud_plugin_config",
)
nextcloud_plugin_config_pending = config_mod.nextcloud_plugin_config_pending
nextcloud_occ_value = config_mod.nextcloud_occ_value
nextcloud_occ_config_set_batch = config_mod.nextcloud_occ_config_set_batch

PREVIOUS_VALUE_EXPRESSION = (
    "{{ ( (item.configvalue | to_json) if (item.configvalue is mapping or "
    "(item.configvalue is sequence and item.configvalue is not string)) "
    "else (item.configvalue | string) ) }}"
)


def _spec(*entries):
    return {"config": {"plugin_configuration": list(entries)}}


def _entry(appid, configkey, configvalue, **extra):
    return {"appid": appid, "configkey": configkey, "configvalue": configvalue, **extra}


def _apps(**apps):
    return {"system": {}, "apps": apps}


def _keys(pending):
    return [(item["appid"], item["configkey"]) for item in pending]


class TestNextcloudOccValue(unittest.TestCase):
    def test_matches_the_previous_jinja_rendering(self):
        values = [
            43200,
            0,
            "yes",
            "",
            "groupOfUniqueNames\nposixGroup",
            "it's",
            None,
            True,
            1.5,
            [{"name": "XWiki", "url": "https://wiki.example/"}],
            {"custom_oidc": [{"name": "kc", "groupMapping": {"/a": "admin"}}]},
            {"ümlaut": "é", "nested": [1, 2.0, None, False]},
            '{"servers": []}',
        ]
        for value in values:
            with self.subTest(value=value):
                rendered = Templar(variables={"item": {"configvalue": value}}).template(
                    trust_as_template("=" + PREVIOUS_VALUE_EXPRESSION)
                )
                self.assertEqual("=" + nextcloud_occ_value(value), rendered)


class TestNextcloudPluginConfigPending(unittest.TestCase):
    def test_key_nextcloud_lacks_is_pending(self):
        pending = nextcloud_plugin_config_pending(
            [_spec(_entry("user_ldap", "background_sync_interval", 43200))],
            _apps(user_ldap={"enabled": "yes"}),
        )
        self.assertEqual(
            pending,
            [
                {
                    "appid": "user_ldap",
                    "configkey": "background_sync_interval",
                    "type": None,
                    "value": "43200",
                }
            ],
        )

    def test_held_string_value_is_dropped(self):
        pending = nextcloud_plugin_config_pending(
            [_spec(_entry("user_ldap", "s01ldap_host", "ldap"))],
            _apps(user_ldap={"s01ldap_host": "ldap"}),
        )
        self.assertEqual(pending, [])

    def test_held_integer_value_is_dropped(self):
        pending = nextcloud_plugin_config_pending(
            [_spec(_entry("user_ldap", "s01ldap_port", 389))],
            _apps(user_ldap={"s01ldap_port": 389}),
        )
        self.assertEqual(pending, [])

    def test_negative_control_near_miss_values_stay_pending(self):
        pending = nextcloud_plugin_config_pending(
            [
                _spec(
                    _entry("a", "case", "Value"),
                    _entry("a", "space", "v"),
                    _entry("a", "number", 389),
                    _entry("a", "padded", "7"),
                )
            ],
            _apps(a={"case": "value", "space": "v ", "number": 390, "padded": 7.0}),
        )
        self.assertEqual(
            _keys(pending),
            [("a", "case"), ("a", "space"), ("a", "number"), ("a", "padded")],
        )

    def test_boolean_value_is_always_pending(self):
        pending = nextcloud_plugin_config_pending(
            [_spec(_entry("a", "flag", "1"), _entry("a", "other", "True"))],
            _apps(a={"flag": True, "other": True}),
        )
        self.assertEqual(_keys(pending), [("a", "flag"), ("a", "other")])

    def test_masked_sensitive_value_is_always_pending(self):
        masked = config_mod.SENSITIVE_VALUE
        pending = nextcloud_plugin_config_pending(
            [_spec(_entry("onlyoffice", "jwt_secret", masked))],
            _apps(onlyoffice={"jwt_secret": masked}),
        )
        self.assertEqual(_keys(pending), [("onlyoffice", "jwt_secret")])

    def test_typed_entry_is_always_pending_with_its_type(self):
        pending = nextcloud_plugin_config_pending(
            [_spec(_entry("spreed", "stun_servers", "[]", type="array"))],
            _apps(spreed={"stun_servers": "[]"}),
        )
        self.assertEqual(pending[0]["type"], "array")
        self.assertEqual(pending[0]["value"], "[]")

    def test_structured_value_held_as_its_json_string_is_dropped(self):
        value = [{"name": "XWiki", "url": "https://wiki.example/"}]
        pending = nextcloud_plugin_config_pending(
            [_spec(_entry("xwiki", "instances", value))],
            _apps(xwiki={"instances": nextcloud_occ_value(value)}),
        )
        self.assertEqual(pending, [])

    def test_structured_value_held_decoded_is_pending(self):
        value = [{"name": "XWiki"}]
        pending = nextcloud_plugin_config_pending(
            [_spec(_entry("xwiki", "instances", value))],
            _apps(xwiki={"instances": value}),
        )
        self.assertEqual(_keys(pending), [("xwiki", "instances")])

    def test_order_follows_specs_and_entries(self):
        pending = nextcloud_plugin_config_pending(
            [
                _spec(
                    _entry("onlyoffice", "jwt_secret", "s"),
                    _entry("onlyoffice", "DocumentServerUrl", "u"),
                ),
                {"enabled": True},
                _spec(_entry("bbb", "api.url", "b")),
            ],
            _apps(),
        )
        self.assertEqual(
            _keys(pending),
            [
                ("onlyoffice", "jwt_secret"),
                ("onlyoffice", "DocumentServerUrl"),
                ("bbb", "api.url"),
            ],
        )

    def test_spec_without_configuration_adds_nothing(self):
        pending = nextcloud_plugin_config_pending(
            [{"enabled": True}, {"config": None}, {"config": {"archive": "x"}}],
            _apps(),
        )
        self.assertEqual(pending, [])

    def test_empty_php_arrays_count_as_no_configuration(self):
        pending = nextcloud_plugin_config_pending(
            [_spec(_entry("deck", "k", "v"), _entry("news", "k", "v"))],
            {"system": [], "apps": {"deck": []}},
        )
        self.assertEqual(_keys(pending), [("deck", "k"), ("news", "k")])
        pending = nextcloud_plugin_config_pending(
            [_spec(_entry("deck", "k", "v"))], {"system": [], "apps": []}
        )
        self.assertEqual(_keys(pending), [("deck", "k")])


class TestNextcloudOccConfigSetBatch(unittest.TestCase):
    def test_an_untyped_entry_hands_occ_only_the_value(self):
        self.assertEqual(
            nextcloud_occ_config_set_batch(
                [
                    {
                        "appid": "deck",
                        "configkey": "k",
                        "type": None,
                        "value": "-1",
                    }
                ]
            ),
            [
                {
                    "argv": ["config:app:set", "deck", "k", "--value", "-1"],
                    "label": "deck/k",
                }
            ],
        )

    def test_a_typed_entry_sets_its_type_without_a_prompt(self):
        batch = nextcloud_occ_config_set_batch(
            [{"appid": "spreed", "configkey": "k", "type": "array", "value": "[]"}]
        )
        self.assertEqual(
            batch[0]["argv"],
            [
                "config:app:set",
                "spreed",
                "k",
                "--no-interaction",
                "--type=array",
                "--value",
                "[]",
            ],
        )

    def test_no_pending_entry_is_no_call(self):
        self.assertEqual(nextcloud_occ_config_set_batch([]), [])


class TestFilterModule(unittest.TestCase):
    def test_filter_is_registered(self):
        self.assertEqual(
            config_mod.FilterModule().filters(),
            {
                "nextcloud_plugin_config_pending": nextcloud_plugin_config_pending,
                "nextcloud_occ_config_set_batch": nextcloud_occ_config_set_batch,
            },
        )


if __name__ == "__main__":
    unittest.main()
