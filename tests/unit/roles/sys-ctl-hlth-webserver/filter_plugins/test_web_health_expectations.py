import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


def load_module_from_path(mod_name: str, path: str):
    """Dynamically load a module from a filesystem path."""
    spec = importlib.util.spec_from_file_location(mod_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


class TestWebHealthExpectationsFilter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from . import PROJECT_ROOT

        cls.ROOT = str(PROJECT_ROOT)
        cls.module_path = str(
            PROJECT_ROOT
            / "roles"
            / "sys-ctl-hlth-webserver"
            / "filter_plugins"
            / "web_health_expectations.py"
        )
        if not Path(cls.module_path).is_file():
            raise FileNotFoundError(
                f"Cannot find web_health_expectations.py at {cls.module_path}"
            )

        # Load the filter module once for all tests
        cls.mod = load_module_from_path("web_health_expectations", cls.module_path)

    def setUp(self):
        # Fresh mock for get per test
        self.get_patch = patch.object(self.mod, "get")
        self.mock_get = self.get_patch.start()

    def tearDown(self):
        self.get_patch.stop()

    def _configure_returns(self, mapping):
        """
        Provide a dict keyed by (app_id, key) -> value.
        get(...) will return mapping.get((app_id, key), default)
        """

        def side_effect(applications, app_id, key, strict=False, default=None):
            return mapping.get((app_id, key), default)

        self.mock_get.side_effect = side_effect

    # ------------ Required selection --------------

    def test_raises_when_group_names_missing(self):
        apps = {"app-a": {}}
        with self.assertRaises(ValueError):
            self.mod.web_health_expectations(apps, group_names=None)

    def test_raises_when_group_names_empty_variants(self):
        apps = {"app-a": {}}
        with self.assertRaises(ValueError):
            self.mod.web_health_expectations(apps, group_names=[])
        with self.assertRaises(ValueError):
            self.mod.web_health_expectations(apps, group_names="")
        with self.assertRaises(ValueError):
            self.mod.web_health_expectations(apps, group_names=" ,  ")

    # ---- Non-mapping apps short-circuit (but group_names still required) ----

    def test_non_mapping_returns_empty_dict(self):
        expectations = self.mod.web_health_expectations(
            applications=["not", "a", "mapping"], group_names=["any"]
        )
        self.assertEqual(expectations, {})

    # ------------ Flat canonical -----------------

    def test_flat_canonical_with_default_status(self):
        apps = {"app-a": {}}
        self._configure_returns(
            {
                ("app-a", "domains.canonical"): ["a.example.org"],
                ("app-a", "domains.aliases"): [],
                ("app-a", "server.status_codes"): {"default": 405},
            }
        )
        out = self.mod.web_health_expectations(apps, group_names=["app-a"])
        self.assertEqual(out["a.example.org"], [405])

    def test_flat_canonical_invalid_default_falls_back_to_default_ok(self):
        apps = {"app-x": {}}
        self._configure_returns(
            {
                ("app-x", "domains.canonical"): ["x.example.org"],
                ("app-x", "domains.aliases"): [],
                ("app-x", "server.status_codes"): {"default": 700},  # invalid HTTP code
            }
        )
        out = self.mod.web_health_expectations(apps, group_names=["app-x"])
        self.assertEqual(out["x.example.org"], [200, 302, 301])

    # ------------ Keyed canonical ----------------

    def test_keyed_canonical_with_per_key_overrides_and_default(self):
        apps = {"app-d": {}}
        self._configure_returns(
            {
                ("app-d", "domains.canonical"): {
                    "api": "api.d.example.org",
                    "web": "web.d.example.org",
                    "view": ["v1.d.example.org", "v2.d.example.org"],
                },
                ("app-d", "domains.aliases"): ["alias.d.example.org"],
                ("app-d", "server.status_codes"): {"api": 404, "default": 405},
            }
        )
        out = self.mod.web_health_expectations(apps, group_names=["app-d"])

        self.assertEqual(out["api.d.example.org"], [404])  # per-key override wins
        self.assertEqual(out["web.d.example.org"], [405])  # default used
        self.assertEqual(out["v1.d.example.org"], [405])  # default used
        self.assertEqual(out["v2.d.example.org"], [405])  # default used
        self.assertEqual(out["alias.d.example.org"], [301])  # aliases always redirect

    def test_keyed_canonical_invalid_key_and_default_falls_back(self):
        apps = {"app-y": {}}
        self._configure_returns(
            {
                ("app-y", "domains.canonical"): {"web": ["y.example.org"]},
                ("app-y", "domains.aliases"): [],
                ("app-y", "server.status_codes"): {
                    "web": 999
                },  # invalid; default missing
            }
        )
        out = self.mod.web_health_expectations(apps, group_names=["app-y"])
        self.assertEqual(out["y.example.org"], [200, 302, 301])

    # ------------ Selection by group_names -------

    def test_selection_by_group_names_list(self):
        apps = {"app-a": {}, "app-b": {}, "app-c": {}}
        self._configure_returns(
            {
                ("app-a", "domains.canonical"): ["a.example.org"],
                ("app-a", "domains.aliases"): [],
                ("app-a", "server.status_codes"): {"default": 200},
                ("app-b", "domains.canonical"): ["b.example.org"],
                ("app-b", "domains.aliases"): [],
                ("app-b", "server.status_codes"): {"default": 405},
                ("app-c", "domains.canonical"): ["c.example.org"],
                ("app-c", "domains.aliases"): ["alias.c.example.org"],
                ("app-c", "server.status_codes"): {},
            }
        )

        out = self.mod.web_health_expectations(apps, group_names=["app-a", "app-c"])
        self.assertIn("a.example.org", out)
        self.assertIn("c.example.org", out)
        self.assertIn("alias.c.example.org", out)
        self.assertNotIn("b.example.org", out)

    def test_selection_by_group_names_string(self):
        apps = {"app-a": {}, "app-b": {}}
        self._configure_returns(
            {
                ("app-a", "domains.canonical"): ["a.example.org"],
                ("app-a", "domains.aliases"): [],
                ("app-a", "server.status_codes"): {"default": 200},
                ("app-b", "domains.canonical"): ["b.example.org"],
                ("app-b", "domains.aliases"): [],
                ("app-b", "server.status_codes"): {"default": 405},
            }
        )
        out = self.mod.web_health_expectations(apps, group_names="app-a, app-c ")
        self.assertIn("a.example.org", out)
        self.assertNotIn("b.example.org", out)

    # ------------ Aliases & filtering ------------

    def test_aliases_are_always_301(self):
        apps = {"app-f": {}}
        self._configure_returns(
            {
                ("app-f", "domains.canonical"): ["f.example.org"],
                ("app-f", "domains.aliases"): [
                    "alias1.example.org",
                    "alias2.example.org",
                ],
                ("app-f", "server.status_codes"): {"default": 200},
            }
        )
        out = self.mod.web_health_expectations(apps, group_names=["app-f"])
        self.assertEqual(out["alias1.example.org"], [301])
        self.assertEqual(out["alias2.example.org"], [301])
        self.assertEqual(out["f.example.org"], [200])

    def test_non_string_entries_in_lists_are_dropped(self):
        apps = {"app-g": {}}
        self._configure_returns(
            {
                ("app-g", "domains.canonical"): [
                    "ok.g.example.org",
                    None,
                    123,
                    {"x": "y"},
                ],
                ("app-g", "domains.aliases"): [
                    {"bad": "obj"},
                    "alias.g.example.org",
                    None,
                ],
                ("app-g", "server.status_codes"): {},  # → fallback
            }
        )
        out = self.mod.web_health_expectations(apps, group_names=["app-g"])
        self.assertIn("ok.g.example.org", out)
        self.assertEqual(out["alias.g.example.org"], [301])
        self.assertNotIn(123, out)

    # ------------ WWW mapping (flag) --------------

    def test_www_mapping_is_added_and_forced_to_301_when_enabled(self):
        apps = {"app-h": {}}
        # includes a canonical that already starts with www.
        self._configure_returns(
            {
                ("app-h", "domains.canonical"): [
                    "h.example.org",
                    "www.keep301.example.org",
                ],
                ("app-h", "domains.aliases"): ["alias.h.example.org"],
                ("app-h", "server.status_codes"): {"default": 405},
            }
        )
        out = self.mod.web_health_expectations(
            apps, group_names=["app-h"], www_enabled=True
        )

        # base domains
        self.assertEqual(out["h.example.org"], [405])
        self.assertEqual(out["alias.h.example.org"], [301])

        # auto-generated www.* entries always 301
        self.assertEqual(out["www.h.example.org"], [301])
        self.assertEqual(out["www.alias.h.example.org"], [301])

        # any pre-existing www.* must be forced to 301 too
        self.assertEqual(out["www.keep301.example.org"], [301])

    def test_no_www_mapping_when_disabled(self):
        apps = {"app-i": {}}
        self._configure_returns(
            {
                ("app-i", "domains.canonical"): ["i.example.org"],
                ("app-i", "domains.aliases"): [],
                ("app-i", "server.status_codes"): {"default": 200},
            }
        )
        out = self.mod.web_health_expectations(
            apps, group_names=["app-i"], www_enabled=False
        )
        self.assertIn("i.example.org", out)
        self.assertNotIn("www.i.example.org", out)

    # ------------ redirect_maps -------------------

    def test_redirect_maps_sources_are_included_as_301(self):
        apps = {}
        out = self.mod.web_health_expectations(
            apps,
            group_names=["any"],  # required, even if no apps
            redirect_maps=[{"source": "mail.example.org"}, "legacy.example.org"],
        )
        self.assertEqual(out["mail.example.org"], [301])
        self.assertEqual(out["legacy.example.org"], [301])

    def test_redirect_maps_override_app_expectations(self):
        apps = {"conflict-app": {}}
        self._configure_returns(
            {
                ("conflict-app", "domains.canonical"): ["conflict.example.org"],
                ("conflict-app", "domains.aliases"): [],
                ("conflict-app", "server.status_codes"): {"default": 200},
            }
        )
        out = self.mod.web_health_expectations(
            apps,
            group_names=["conflict-app"],
            redirect_maps=[{"source": "conflict.example.org"}],
        )
        self.assertEqual(out["conflict.example.org"], [301])

    def test_redirect_maps_get_www_when_enabled(self):
        apps = {}
        out = self.mod.web_health_expectations(
            apps,
            group_names=["any"],
            www_enabled=True,
            redirect_maps=[{"source": "redir.example.org"}],
        )
        self.assertEqual(out["redir.example.org"], [301])
        self.assertEqual(out["www.redir.example.org"], [301])

    def test_redirect_maps_independent_of_group_filter(self):
        apps = {"ignored-app": {}}
        self._configure_returns(
            {
                ("ignored-app", "domains.canonical"): ["ignored.example.org"],
                ("ignored-app", "domains.aliases"): [],
                ("ignored-app", "server.status_codes"): {"default": 200},
            }
        )
        out = self.mod.web_health_expectations(
            apps,
            group_names=["some-other-app"],  # excludes the only app
            redirect_maps=[{"source": "manual.example.org"}],
        )
        self.assertNotIn("ignored.example.org", out)
        self.assertEqual(out["manual.example.org"], [301])

    # --------- NEW: status_codes list support ---------

    def test_flat_canonical_with_default_list(self):
        apps = {"app-l1": {}}
        self._configure_returns(
            {
                ("app-l1", "domains.canonical"): ["l1.example.org"],
                ("app-l1", "domains.aliases"): [],
                ("app-l1", "server.status_codes"): {"default": [204, "302", 301]},
            }
        )
        out = self.mod.web_health_expectations(apps, group_names=["app-l1"])
        self.assertEqual(out["l1.example.org"], [204, 302, 301])

    def test_keyed_canonical_with_list_and_default_list(self):
        apps = {"app-l2": {}}
        self._configure_returns(
            {
                ("app-l2", "domains.canonical"): {
                    "api": ["api1.l2.example.org", "api2.l2.example.org"],
                    "web": "web.l2.example.org",
                },
                ("app-l2", "domains.aliases"): [],
                ("app-l2", "server.status_codes"): {
                    "api": [301, 403],
                    "default": [200, 204],
                },
            }
        )
        out = self.mod.web_health_expectations(apps, group_names=["app-l2"])
        self.assertEqual(out["api1.l2.example.org"], [301, 403])  # per-key list wins
        self.assertEqual(out["api2.l2.example.org"], [301, 403])
        self.assertEqual(out["web.l2.example.org"], [200, 204])  # default list

    def test_status_codes_strings_and_ints_and_out_of_range_ignored(self):
        apps = {"app-l3": {}}
        # 99 (<100) and 700 (>599) are ignored, "301" string is converted
        self._configure_returns(
            {
                ("app-l3", "domains.canonical"): ["l3.example.org"],
                ("app-l3", "domains.aliases"): [],
                ("app-l3", "server.status_codes"): {"default": ["301", 200, 99, 700]},
            }
        )
        out = self.mod.web_health_expectations(apps, group_names=["app-l3"])
        self.assertEqual(out["l3.example.org"], [301, 200])

    def test_status_codes_deduplicate_preserve_order(self):
        apps = {"app-l4": {}}
        self._configure_returns(
            {
                ("app-l4", "domains.canonical"): ["l4.example.org"],
                ("app-l4", "domains.aliases"): [],
                ("app-l4", "server.status_codes"): {
                    "default": [301, 302, 301, 302, 200]
                },
            }
        )
        out = self.mod.web_health_expectations(apps, group_names=["app-l4"])
        self.assertEqual(out["l4.example.org"], [301, 302, 200])  # dedup but keep order

    def test_key_specific_int_overrides_default_list(self):
        apps = {"app-l5": {}}
        self._configure_returns(
            {
                ("app-l5", "domains.canonical"): {"console": ["c1.l5.example.org"]},
                ("app-l5", "domains.aliases"): [],
                ("app-l5", "server.status_codes"): {
                    "console": 301,
                    "default": [200, 204],
                },
            }
        )
        out = self.mod.web_health_expectations(apps, group_names=["app-l5"])
        self.assertEqual(
            out["c1.l5.example.org"], [301]
        )  # per-key int beats default list

    def test_key_specific_list_overrides_default_int(self):
        apps = {"app-l6": {}}
        self._configure_returns(
            {
                ("app-l6", "domains.canonical"): {"api": "api.l6.example.org"},
                ("app-l6", "domains.aliases"): [],
                ("app-l6", "server.status_codes"): {"api": [301, 403], "default": 200},
            }
        )
        out = self.mod.web_health_expectations(apps, group_names=["app-l6"])
        self.assertEqual(out["api.l6.example.org"], [301, 403])

    def test_invalid_default_list_falls_back_to_default_ok(self):
        apps = {"app-l7": {}}
        # everything invalid → fall back to DEFAULT_OK
        self._configure_returns(
            {
                ("app-l7", "domains.canonical"): ["l7.example.org"],
                ("app-l7", "domains.aliases"): [],
                ("app-l7", "server.status_codes"): {
                    "default": ["x", 42.42, {}, 700, 99]
                },
            }
        )
        out = self.mod.web_health_expectations(apps, group_names=["app-l7"])
        self.assertEqual(out["l7.example.org"], [200, 302, 301])

    def test_key_with_invalid_list_uses_default_list(self):
        apps = {"app-l8": {}}
        self._configure_returns(
            {
                ("app-l8", "domains.canonical"): {"web": "web.l8.example.org"},
                ("app-l8", "domains.aliases"): [],
                ("app-l8", "server.status_codes"): {
                    "web": ["foo", None],
                    "default": [204, 206],
                },
            }
        )
        out = self.mod.web_health_expectations(apps, group_names=["app-l8"])
        self.assertEqual(out["web.l8.example.org"], [204, 206])

    def test_key_and_default_both_invalid_falls_back_to_default_ok(self):
        apps = {"app-l9": {}}
        self._configure_returns(
            {
                ("app-l9", "domains.canonical"): {"api": "api.l9.example.org"},
                ("app-l9", "domains.aliases"): [],
                ("app-l9", "server.status_codes"): {
                    "api": ["bad"],
                    "default": ["also", "bad"],
                },
            }
        )
        out = self.mod.web_health_expectations(apps, group_names=["app-l9"])
        self.assertEqual(out["api.l9.example.org"], [200, 302, 301])

    def test_aliases_still_forced_to_301_even_with_default_list(self):
        apps = {"app-l10": {}}
        self._configure_returns(
            {
                ("app-l10", "domains.canonical"): ["l10.example.org"],
                ("app-l10", "domains.aliases"): ["alias.l10.example.org"],
                ("app-l10", "server.status_codes"): {"default": [204, 206]},
            }
        )
        out = self.mod.web_health_expectations(apps, group_names=["app-l10"])
        self.assertEqual(out["l10.example.org"], [204, 206])
        self.assertEqual(out["alias.l10.example.org"], [301])

    def test_keyed_canonical_with_mixed_scalar_and_list_domains(self):
        apps = {"app-l11": {}}
        self._configure_returns(
            {
                ("app-l11", "domains.canonical"): {
                    "api": "api.l11.example.org",
                    "view": ["v1.l11.example.org", "v2.l11.example.org"],
                },
                ("app-l11", "domains.aliases"): [],
                ("app-l11", "server.status_codes"): {
                    "view": [301, 307],
                    "default": [200, 204],
                },
            }
        )
        out = self.mod.web_health_expectations(apps, group_names=["app-l11"])
        self.assertEqual(out["api.l11.example.org"], [200, 204])  # default
        self.assertEqual(out["v1.l11.example.org"], [301, 307])  # per-key list
        self.assertEqual(out["v2.l11.example.org"], [301, 307])

    def test_expectations_keys_are_sorted_alphabetically(self):
        apps = {"app-sort": {}}
        self._configure_returns(
            {
                ("app-sort", "domains.canonical"): [
                    "b.example.org",
                    "a.example.org",
                    "c.example.org",
                ],
                ("app-sort", "domains.aliases"): ["alias.example.org"],
                ("app-sort", "server.status_codes"): {"default": 200},
            }
        )
        out = self.mod.web_health_expectations(apps, group_names=["app-sort"])

        keys = list(out.keys())
        self.assertEqual(keys, sorted(keys))

    def test_expectations_keys_sorted_with_redirects_and_www(self):
        apps = {}
        out = self.mod.web_health_expectations(
            apps,
            group_names=["dummy-app"],
            www_enabled=True,
            redirect_maps=[
                {"source": "redir-b.example.org"},
                {"source": "redir-a.example.org"},
            ],
        )

        keys = list(out.keys())
        self.assertEqual(keys, sorted(keys))


if __name__ == "__main__":
    unittest.main()
