"""Opt-in external drift checker for unified addons.

For every addon in ``roles/*/meta/addons/*.yml`` carrying
``update.monitored: true`` this test surfaces, as warnings only, when its
pinned ``version`` is behind the upstream its ``update:`` block or its
``github-releases`` catalog names. A monitored addon without a pin tracks the
application's default and has nothing to fall behind;
``tests/lint/repository/test_version_pins_are_watched.py`` keeps every pinned
one resolvable.

It mirrors the Docker image / repository-ref external checks:

* warn-only: it NEVER fails the session, so registry slowness or outages do
  not break validation;
* external: it runs through ``make test-external``, which ``make test`` runs
  beside the other suites;
* bounded: discovery is limited to the curated adapters in
  ``utils.update.addons.SUPPORTED_CATALOGS``, so broad public marketplaces
  (the full WordPress plugin directory, the whole GNOME extensions site)
  never produce unreviewable warning noise.

The version resolution is :func:`utils.update.source.addon_entries` plus
:func:`utils.update.source.outdated`, which the CI auto-update job reuses to
open pull requests. Catalog discovery is
:func:`utils.update.catalog.discover_catalog_entries` over
``utils.update.catalog.CATALOG_ADAPTERS``; its parsers and relevance rule are
exercised with fixture catalogs by ``tests/unit/python/utils/update/test_catalog.py``
and the reconciliation core by ``tests/unit/python/utils/update/test_addons.py``.
A catalog without an adapter degrades to "monitored, not yet checked".
"""

from __future__ import annotations

import unittest

from utils.annotations.message import warning as gha_warning
from utils.roles.mapping import ROLE_DIR_META_ADDONS
from utils.update.addons import collect_addon_entries
from utils.update.catalog import discover_catalog_entries
from utils.update.fetch import document
from utils.update.source import addon_entries, outdated

from . import PROJECT_ROOT


class TestAddonVersions(unittest.TestCase):
    """Warn-only: surface monitored addons and their catalogs for drift review."""

    def test_monitored_addons_are_surfaced(self) -> None:
        roles_root = PROJECT_ROOT / "roles"
        entries = collect_addon_entries(roles_root)

        monitored = [e for e in entries if e.monitored]

        by_catalog: dict[str, list[str]] = {}
        for entry in monitored:
            catalog = entry.catalog or "(none)"
            by_catalog.setdefault(catalog, []).append(f"{entry.role}/{entry.addon_id}")

        if monitored:
            lines = "\n".join(
                f"  {catalog}: {', '.join(sorted(ids))}"
                for catalog, ids in sorted(by_catalog.items())
            )
            print(
                f"\n🔍 {len(monitored)} monitored addon(s) across "
                f"{len(by_catalog)} catalog(s):\n{lines}\n\n"
                "Live version/discovery drift is reported below as warnings "
                "(warn-only; suppress per-addon by setting update.monitored: "
                "false).",
                flush=True,
            )
            for entry in monitored:
                if not entry.catalog:
                    gha_warning(
                        f"{entry.role}/{entry.addon_id}: update.monitored is set "
                        f"but no update.catalog adapter is configured",
                        title="Addon monitored without catalog",
                        file=str(entry.config_path.relative_to(PROJECT_ROOT)),
                    )

        self.assertIsNotNone(entries)

    def test_monitored_addon_pins_are_current(self) -> None:
        entries = addon_entries(PROJECT_ROOT)
        updates = outdated(entries, PROJECT_ROOT)

        if updates:
            rows = "\n".join(
                f"{u.entry.role}/addons/{u.entry.entity}.{u.entry.key}: "
                f"{u.entry.current} -> {u.latest}"
                for u in updates
            )
            print(
                f"\n⚠️  Outdated addon versions:\n{rows}\n"
                "\n💡 To suppress a warning add above the pinned key:\n"
                "  # nocheck: version-source",
                flush=True,
            )
            for u in updates:
                gha_warning(
                    f"{u.entry.role}/addons/{u.entry.entity}.{u.entry.key} is at "
                    f"{u.entry.current}, upstream offers {u.latest}",
                    title="Outdated addon version",
                    file=str(u.entry.config_path.relative_to(PROJECT_ROOT)),
                    line=u.entry.line,
                )

        self.assertIsNotNone(entries)

    def test_relevant_catalog_entries_are_declared(self) -> None:
        found = discover_catalog_entries(PROJECT_ROOT / "roles", document)

        for problem in found.unreachable:
            gha_warning(problem, title="Addon catalog unreachable")
        for suggestion in found.new_addons:
            gha_warning(
                f"{suggestion.role}/addons/{suggestion.addon_id}: catalog "
                f"{suggestion.catalog} lists {suggestion.upstream_id} "
                f"(mechanism {suggestion.mechanism}, source {suggestion.source}, "
                f"{suggestion.catalog_url}) and meta/addons/ does not declare it; "
                f"relevant because {suggestion.reason}",
                title="Undeclared catalog addon",
                file=f"roles/{suggestion.role}/{ROLE_DIR_META_ADDONS}",
            )
        for update in found.version_updates:
            gha_warning(
                f"{update.role}/addons/{update.addon_id} is at {update.current}, "
                f"catalog {update.catalog} offers {update.latest}",
                title="Outdated addon version",
                file=str(update.config_path.relative_to(PROJECT_ROOT)),
                line=update.line,
            )

        self.assertIsNotNone(found)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
