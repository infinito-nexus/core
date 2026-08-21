"""Unit tests for the pure addon drift-discovery core.

The live external test (`tests/external/update/addons/`) is warn-only and
opt-in; the reconciliation logic it relies on is exercised here with fixture
catalogs covering the three behaviours the requirement calls out: a version
bump, a newly discovered addon, and a marketplace entry intentionally ignored
by the curated relevance rules.
"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from utils.roles.mapping import ROLE_DIR_META_ADDONS
from utils.update.addons import (
    AddonEntry,
    CatalogCandidate,
    collect_addon_entries,
    discover_addon_updates,
    version_is_newer,
)


def _entry(
    addon_id, version="", monitored=True, upstream_id=None, catalog="wordpress-org"
):
    spec = {
        "mechanism": "plugin",
        "source": "upstream",
        "version": version,
        "update": {"monitored": monitored, "catalog": catalog},
    }
    if upstream_id:
        spec["update"]["upstream_id"] = upstream_id
    return AddonEntry(
        role="web-app-demo",
        addon_id=addon_id,
        config_path=Path("roles/web-app-demo")
        / ROLE_DIR_META_ADDONS
        / f"{addon_id}.yml",
        spec=spec,
    )


class TestVersionIsNewer(unittest.TestCase):
    def test_strictly_newer(self):
        self.assertTrue(version_is_newer("2.3.1", "2.4.0"))

    def test_equal_is_not_newer(self):
        self.assertFalse(version_is_newer("2.3.1", "2.3.1"))

    def test_blank_current_never_suggests(self):
        self.assertFalse(version_is_newer("", "2.4.0"))

    def test_non_semver_latest_ignored(self):
        self.assertFalse(version_is_newer("2.3.1", "master"))


class TestDiscoverAddonUpdates(unittest.TestCase):
    def test_version_bump_suggested_for_monitored_pin(self):
        declared = [_entry("oidc", version="2.3.1")]
        candidates = [
            CatalogCandidate(
                upstream_id="oidc",
                latest="2.4.0",
                mechanism="plugin",
                source="built",
                catalog_url="https://example.test/oidc",
            )
        ]
        result = discover_addon_updates(
            role="web-app-demo",
            catalog="wordpress-org",
            declared=declared,
            candidates=candidates,
        )
        self.assertEqual(len(result.version_updates), 1)
        self.assertEqual(result.version_updates[0].current, "2.3.1")
        self.assertEqual(result.version_updates[0].latest, "2.4.0")
        self.assertEqual(result.new_addons, [])

    def test_unmonitored_pin_is_not_bumped(self):
        declared = [_entry("oidc", version="2.3.1", monitored=False)]
        candidates = [
            CatalogCandidate(
                upstream_id="oidc",
                latest="2.4.0",
                mechanism="plugin",
                source="upstream",
                catalog_url="https://example.test/oidc",
            )
        ]
        result = discover_addon_updates(
            role="web-app-demo",
            catalog="wordpress-org",
            declared=declared,
            candidates=candidates,
        )
        self.assertEqual(result.version_updates, [])

    def test_new_addon_discovered(self):
        declared = [_entry("oidc", version="2.3.1")]
        candidates = [
            CatalogCandidate(
                upstream_id="oidc",
                latest="2.3.1",
                mechanism="plugin",
                source="upstream",
                catalog_url="https://example.test/oidc",
            ),
            CatalogCandidate(
                upstream_id="wp-discourse",
                latest="2.5.0",
                mechanism="plugin",
                source="upstream",
                catalog_url="https://example.test/wp-discourse",
                reason="curated: bridges web-app-discourse",
            ),
        ]
        result = discover_addon_updates(
            role="web-app-demo",
            catalog="wordpress-org",
            declared=declared,
            candidates=candidates,
        )
        self.assertEqual(len(result.new_addons), 1)
        self.assertEqual(result.new_addons[0].addon_id, "wp-discourse")
        self.assertEqual(result.version_updates, [])

    def test_irrelevant_marketplace_entry_ignored(self):
        declared = [_entry("oidc", version="2.3.1")]
        candidates = [
            CatalogCandidate(
                upstream_id="some-random-marketplace-plugin",
                latest="9.9.9",
                mechanism="plugin",
                source="upstream",
                catalog_url="https://example.test/random",
                relevant=False,
                reason="not in curated relevance set",
            )
        ]
        result = discover_addon_updates(
            role="web-app-demo",
            catalog="wordpress-org",
            declared=declared,
            candidates=candidates,
        )
        self.assertEqual(result.new_addons, [])
        self.assertEqual(result.version_updates, [])

    def test_upstream_id_override_matches_declared(self):
        declared = [_entry("oidc", version="2.3.1", upstream_id="pretix-oidc")]
        candidates = [
            CatalogCandidate(
                upstream_id="pretix-oidc",
                latest="2.4.0",
                mechanism="plugin",
                source="built",
                catalog_url="https://example.test/pretix-oidc",
            )
        ]
        result = discover_addon_updates(
            role="web-app-demo",
            catalog="odoo-apps",
            declared=declared,
            candidates=candidates,
        )
        self.assertEqual(len(result.version_updates), 1)
        self.assertEqual(result.version_updates[0].addon_id, "oidc")


class TestCollectAddonEntries(unittest.TestCase):
    def test_collects_and_skips_malformed(self):
        with tempfile.TemporaryDirectory() as tmp:
            addons = Path(tmp) / "roles" / "web-app-demo" / ROLE_DIR_META_ADDONS
            addons.mkdir(parents=True)
            (addons / "good.yml").write_text(
                textwrap.dedent(
                    """
                    ---
                    mechanism: plugin
                    source: upstream
                    version: "1.0"
                    update:
                      monitored: true
                      catalog: wordpress-org
                    """
                ),
                encoding="utf-8",
            )
            (addons / "bad.yml").write_text("not a mapping\n", encoding="utf-8")
            entries = collect_addon_entries(Path(tmp) / "roles")
            ids = sorted(e.addon_id for e in entries)
            self.assertEqual(ids, ["good"])
            self.assertTrue(entries[0].monitored)
            self.assertEqual(entries[0].catalog, "wordpress-org")
            self.assertEqual(entries[0].upstream_id, "good")


if __name__ == "__main__":
    unittest.main()
