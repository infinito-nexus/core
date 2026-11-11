"""Unit tests for the bounded addon catalog discovery and its writer.

Every listing is a fixture; no test touches the network.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_DIR_META_ADDONS
from utils.update.addons import (
    ADDON_KEYS,
    MECHANISMS,
    SOURCES,
    SUPPORTED_CATALOGS,
    UPDATE_KEYS,
    CatalogSuggestion,
)
from utils.update.catalog import (
    CATALOG_ADAPTERS,
    CatalogAdapter,
    discover_catalog_entries,
    parse_github_directories,
    parse_nextcloud_apps,
    relevant_term,
    write_suggestion,
)

FRIENDICA_LISTING = json.dumps(
    [
        {"name": "ldapauth", "type": "dir"},
        {"name": "discourse", "type": "dir"},
        {"name": "blockem", "type": "dir"},
        {"name": ".github", "type": "dir"},
        {"name": "README.md", "type": "file"},
    ]
)

NEXTCLOUD_LISTING = json.dumps(
    [
        {
            "id": "integration_openproject",
            "releases": [
                {"version": "2.6.0"},
                {"version": "2.10.1"},
                {"version": "2.11.0-beta.1"},
            ],
        },
        {"id": "unreleased", "releases": []},
    ]
)


def _role_tree(tmp: str) -> Path:
    """Create a roles tree: a host monitoring friendica-addons, two partners.

    Args:
        tmp: the temporary directory the tree is created in.
    """
    roles = Path(tmp) / "roles"
    addons = roles / "web-app-demo" / ROLE_DIR_META_ADDONS
    addons.mkdir(parents=True)
    (addons / "ldapauth.yml").write_text(
        "mechanism: addon\nsource: upstream\nupdate:\n"
        "  monitored: true\n  catalog: friendica-addons\n",
        encoding="utf-8",
    )
    (roles / "web-app-discourse").mkdir()
    (roles / "svc-db-openldap").mkdir()
    return roles


class TestCatalogParsers(unittest.TestCase):
    def test_github_listing_keeps_directories_only(self):
        self.assertEqual(
            parse_github_directories(FRIENDICA_LISTING),
            [("ldapauth", ""), ("discourse", ""), ("blockem", "")],
        )

    def test_nextcloud_listing_reports_the_newest_stable_release(self):
        self.assertEqual(
            parse_nextcloud_apps(NEXTCLOUD_LISTING),
            [("integration_openproject", "2.10.1"), ("unreleased", "")],
        )

    def test_every_adapter_serves_a_supported_catalog(self):
        self.assertLessEqual(set(CATALOG_ADAPTERS), SUPPORTED_CATALOGS)
        for adapter in CATALOG_ADAPTERS.values():
            self.assertIn(adapter.mechanism, MECHANISMS)
            self.assertIn("{upstream_id}", adapter.page)


class TestRelevantTerm(unittest.TestCase):
    def test_a_long_term_matches_the_start_of_a_token(self):
        self.assertEqual(relevant_term("ldapauth", frozenset({"ldap"}), "demo"), "ldap")

    def test_a_short_term_needs_the_whole_token(self):
        self.assertIsNone(relevant_term("editor", frozenset({"tor"}), "demo"))
        self.assertEqual(relevant_term("tor-relay", frozenset({"tor"}), "demo"), "tor")

    def test_the_hosting_role_is_no_partner_of_itself(self):
        self.assertIsNone(
            relevant_term("friendica_tools", frozenset({"friendica"}), "friendica")
        )


class TestDiscoverCatalogEntries(unittest.TestCase):
    def test_only_a_relevant_undeclared_entry_is_suggested(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = _role_tree(tmp)
            found = discover_catalog_entries(roles, lambda url: FRIENDICA_LISTING)
        self.assertEqual([s.upstream_id for s in found.new_addons], ["discourse"])
        suggestion = found.new_addons[0]
        self.assertEqual(suggestion.role, "web-app-demo")
        self.assertEqual(suggestion.catalog, "friendica-addons")
        self.assertEqual(suggestion.mechanism, "addon")
        self.assertEqual(suggestion.source, "upstream")
        self.assertEqual(
            suggestion.catalog_url,
            "https://github.com/friendica/friendica-addons/tree/develop/discourse",
        )
        self.assertIn("'discourse'", suggestion.reason)
        self.assertEqual(found.unreachable, [])

    def test_a_role_monitoring_no_adapted_catalog_is_never_fetched(self):
        fetched: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            roles = _role_tree(tmp)
            discover_catalog_entries(
                roles,
                lambda url: fetched.append(url) or "[]",
                adapters={
                    "nextcloud-appstore": CatalogAdapter(
                        url="https://example.test/apps.json",
                        page="https://example.test/{upstream_id}",
                        parse=parse_nextcloud_apps,
                        mechanism="plugin",
                    )
                },
            )
        self.assertEqual(fetched, [])

    def test_an_unreachable_listing_is_reported_not_raised(self):
        def offline(url):
            raise OSError("network is unreachable")

        with tempfile.TemporaryDirectory() as tmp:
            found = discover_catalog_entries(_role_tree(tmp), offline)
        self.assertEqual(found.new_addons, [])
        self.assertEqual(len(found.unreachable), 1)
        self.assertIn("network is unreachable", found.unreachable[0])


class TestWriteSuggestion(unittest.TestCase):
    def _suggestion(self, addon_id="discourse"):
        return CatalogSuggestion(
            role="web-app-demo",
            addon_id=addon_id,
            upstream_id=addon_id,
            mechanism="addon",
            source="upstream",
            catalog="friendica-addons",
            catalog_url=f"https://example.test/{addon_id}",
            reason="its id names the integration partner 'discourse'",
        )

    def test_the_written_addon_is_off_optional_monitored_and_secret_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = _role_tree(tmp)
            path = write_suggestion(roles, self._suggestion())
            text = read_text(str(path))
            spec = load_yaml_any(str(path))
        self.assertEqual(path.name, "discourse.yml")
        self.assertTrue(text.startswith("---\n"))
        self.assertIs(spec["enabled"], False)
        self.assertIs(spec["required"], False)
        self.assertEqual(
            spec["update"],
            {
                "monitored": True,
                "catalog": "friendica-addons",
                "upstream_id": "discourse",
            },
        )
        self.assertNotIn("config", spec)
        self.assertNotIn("bridges", spec)
        self.assertLessEqual(set(spec), ADDON_KEYS)
        self.assertLessEqual(set(spec["update"]), UPDATE_KEYS)
        self.assertIn(spec["mechanism"], MECHANISMS)
        self.assertIn(spec["source"], SOURCES)

    def test_an_existing_declaration_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = _role_tree(tmp)
            with self.assertRaises(FileExistsError):
                write_suggestion(roles, self._suggestion("ldapauth"))

    def test_an_id_that_would_leave_the_addons_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = _role_tree(tmp)
            with self.assertRaises(ValueError):
                write_suggestion(roles, self._suggestion("../../evil"))


if __name__ == "__main__":
    unittest.main()
