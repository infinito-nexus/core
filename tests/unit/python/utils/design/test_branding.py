import tempfile
import unittest
from pathlib import Path

from utils.design.branding import asset_urls, is_disabled, resolve_branding

GLOBAL_SLOTS = {"icon": {"width": 512, "height": 512}}


class TestResolveBranding(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "assets").mkdir()
        (self.root / "assets" / "logo.png").write_bytes(b"png")
        (self.root / "custom.png").write_bytes(b"png")
        for role, h1 in (
            ("web-svc-design", "Corporate Design"),
            ("web-app-a", "Alpha"),
            ("web-app-b", "Beta"),
        ):
            (self.root / "roles" / role).mkdir(parents=True)
            (self.root / "roles" / role / "README.md").write_text(
                f"# {h1}\n\nText\n", encoding="utf-8"
            )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _apps(self, global_extra: dict, role_design: dict | None) -> dict:
        design = {
            "logo": "assets/logo.png",
            "title": True,
            "bootstrap": False,
            "slots": GLOBAL_SLOTS,
            **global_extra,
        }
        role_services = {} if role_design is None else {"design": role_design}
        return {
            "web-svc-design": {"services": {"design": design}},
            "web-app-a": {"services": role_services},
        }

    def test_global_defaults_apply_with_readme_title(self) -> None:
        result = resolve_branding(self._apps({}, {}), "web-app-a", self.root)
        self.assertEqual(result["logo"], str(self.root / "assets" / "logo.png"))
        self.assertEqual(result["title"], "Alpha")
        self.assertEqual(result["label"], "Alpha")

    def test_global_title_applies_to_every_role(self) -> None:
        result = resolve_branding(
            self._apps({"title": "Platform"}, {}), "web-app-a", self.root
        )
        self.assertEqual(result["title"], "Platform")

    def test_bootstrap_mapping_is_off_unless_a_role_or_the_platform_opts_in(
        self,
    ) -> None:
        self.assertFalse(
            resolve_branding(self._apps({}, {}), "web-app-a", self.root)["bootstrap"]
        )
        self.assertTrue(
            resolve_branding(
                self._apps({}, {"bootstrap": True}), "web-app-a", self.root
            )["bootstrap"]
        )
        self.assertFalse(
            resolve_branding(
                self._apps({"bootstrap": True}, {"bootstrap": False}),
                "web-app-a",
                self.root,
            )["bootstrap"]
        )

    def test_role_override_wins_over_global(self) -> None:
        apps = self._apps({"title": "Platform"}, {"title": "Own", "logo": "custom.png"})
        result = resolve_branding(apps, "web-app-a", self.root)
        self.assertEqual(result["title"], "Own")
        self.assertEqual(result["logo"], str(self.root / "custom.png"))

    def test_role_true_title_returns_to_its_readme_title(self) -> None:
        result = resolve_branding(
            self._apps({"title": "Platform"}, {"title": True}), "web-app-a", self.root
        )
        self.assertEqual(result["title"], "Alpha")

    def test_role_without_design_entry_inherits_global(self) -> None:
        result = resolve_branding(
            self._apps({"title": "Platform"}, None), "web-app-a", self.root
        )
        self.assertEqual(result["title"], "Platform")

    def test_false_and_zero_disable_per_scope(self) -> None:
        for off in (False, 0, "false", "0"):
            with self.subTest(off=off):
                role_off = resolve_branding(
                    self._apps({}, {"logo": off, "title": off}), "web-app-a", self.root
                )
                self.assertIs(role_off["logo"], False)
                self.assertIs(role_off["title"], False)
                self.assertEqual(role_off["label"], "Alpha")
                global_off = resolve_branding(
                    self._apps({"logo": off, "title": off}, {}), "web-app-a", self.root
                )
                self.assertIs(global_off["logo"], False)
                self.assertIs(global_off["title"], False)

    def test_role_can_reenable_a_globally_disabled_logo(self) -> None:
        apps = self._apps({"logo": False}, {"logo": "custom.png"})
        self.assertEqual(
            resolve_branding(apps, "web-app-a", self.root)["logo"],
            str(self.root / "custom.png"),
        )

    def test_role_slots_extend_global_slots(self) -> None:
        apps = self._apps(
            {}, {"slots": {"login": {"width": 400, "height": 120, "text_only": True}}}
        )
        slots = resolve_branding(apps, "web-app-a", self.root)["slots"]
        self.assertEqual(set(slots), {"icon", "login"})
        self.assertFalse(slots["icon"]["text_only"])
        self.assertTrue(slots["login"]["text_only"])

    def test_missing_logo_file_fails_loudly(self) -> None:
        with self.assertRaisesRegex(ValueError, "not found"):
            resolve_branding(
                self._apps({}, {"logo": "nope.png"}), "web-app-a", self.root
            )

    def test_non_positive_slot_fails_loudly(self) -> None:
        apps = self._apps({}, {"slots": {"bad": {"width": 0, "height": 10}}})
        with self.assertRaisesRegex(ValueError, "positive"):
            resolve_branding(apps, "web-app-a", self.root)

    def test_slot_name_outside_kebab_case_fails_loudly(self) -> None:
        for name in ("favicon_ico", "Logo", "wide.banner", ""):
            with self.subTest(name=name):
                apps = self._apps({}, {"slots": {name: {"width": 10, "height": 10}}})
                with self.assertRaisesRegex(ValueError, "kebab-case"):
                    resolve_branding(apps, "web-app-a", self.root)


class TestAssetUrls(unittest.TestCase):
    def test_a_slot_named_favicon_keeps_the_icon_url(self) -> None:
        urls = asset_urls("https://cdn.test/design", {"favicon": {}, "logo": {}})
        self.assertEqual(urls["favicon_ico"], "https://cdn.test/design/favicon.ico")
        self.assertEqual(
            urls["favicon"],
            {
                "png": "https://cdn.test/design/favicon.png",
                "svg": "https://cdn.test/design/favicon.svg",
            },
        )
        self.assertEqual(set(urls), {"favicon_ico", "favicon", "logo"})


class TestIsDisabled(unittest.TestCase):
    def test_disabled_spellings(self) -> None:
        for value in (False, 0, "0", "false", "False", "no"):
            self.assertTrue(is_disabled(value), value)

    def test_enabled_values(self) -> None:
        for value in ("assets/img/logo.png", "Title", None, True, 1):
            self.assertFalse(is_disabled(value), value)


if __name__ == "__main__":
    unittest.main()
