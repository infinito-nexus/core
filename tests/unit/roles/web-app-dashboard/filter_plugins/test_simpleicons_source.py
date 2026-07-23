import importlib.util
import unittest

from . import PROJECT_ROOT


def _load_simpleicons_module():
    module_path = (
        PROJECT_ROOT
        / "roles"
        / "web-app-dashboard"
        / "filter_plugins"
        / "simpleicons_source.py"
    )

    if not module_path.is_file():
        raise RuntimeError(
            f"Could not find simpleicons_source.py at expected path: {module_path}"
        )

    spec = importlib.util.spec_from_file_location("simpleicons_source", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_simpleicons = _load_simpleicons_module()
add_simpleicon_source = _simpleicons.add_simpleicon_source
simpleicon_slugs = _simpleicons.simpleicon_slugs


class TestSimpleiconSlugs(unittest.TestCase):
    def test_derives_unique_slugs_from_titles_in_order(self):
        cards = [
            {"title": "Keycloak"},
            {"title": "Next Cloud"},
            {"icon": {}},
            {"title": "Keycloak"},
        ]
        self.assertEqual(simpleicon_slugs(cards), ["keycloak", "nextcloud"])

    def test_skips_cards_without_title(self):
        cards = [{"icon": {"class": "fa-solid fa-lock"}}, {"title": ""}]
        self.assertEqual(simpleicon_slugs(cards), [])

    def test_strips_non_ascii_so_probe_url_is_ascii_encodable(self):
        # U+2011 NON-BREAKING HYPHEN in a title crashed the uri probe (ascii encode)
        slugs = simpleicon_slugs([{"title": "Mini‑QR"}, {"title": "Café"}])
        self.assertEqual(slugs, ["miniqr", "cafe"])
        self.assertTrue(all(s.isascii() for s in slugs))


class TestAddSimpleiconSource(unittest.TestCase):
    def test_sets_source_for_reachable_slug(self):
        cards = [{"title": "Keycloak", "icon": {"class": "fa-solid fa-lock"}}]

        result = add_simpleicon_source(cards, ["keycloak"], "https://icons.example")

        self.assertEqual(
            result[0]["icon"]["source"], "https://icons.example/keycloak.svg"
        )
        self.assertEqual(result[0]["icon"]["class"], "fa-solid fa-lock")

    def test_writes_public_url_into_source(self):
        cards = [{"title": "Keycloak", "icon": {}}]

        result = add_simpleicon_source(cards, ["keycloak"], "https://icon.example.com")

        self.assertEqual(
            result[0]["icon"]["source"], "https://icon.example.com/keycloak.svg"
        )

    def test_keeps_card_without_source_when_slug_not_reachable(self):
        cards = [{"title": "Missing", "icon": {"class": "fa-solid fa-circle-question"}}]

        result = add_simpleicon_source(cards, ["keycloak"], "https://icon.example.com")

        self.assertNotIn("source", result[0]["icon"])

    def test_empty_reachable_set_falls_back_cleanly(self):
        cards = [{"title": "Keycloak", "icon": {"class": "fa-solid fa-lock"}}]

        result = add_simpleicon_source(cards, None, "https://icon.example.com")

        self.assertNotIn("source", result[0]["icon"])

    def test_resolves_bare_domain_with_web_protocol(self):
        cards = [{"title": "Keycloak", "icon": {}}]

        result = add_simpleicon_source(
            cards, ["keycloak"], "icons.example", web_protocol="http"
        )

        self.assertEqual(
            result[0]["icon"]["source"], "http://icons.example/keycloak.svg"
        )


if __name__ == "__main__":
    unittest.main()
