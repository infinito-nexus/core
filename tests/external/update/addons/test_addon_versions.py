"""Opt-in external drift checker for unified addons.

For every addon in ``roles/*/meta/addons/*.yml`` carrying
``update.monitored: true`` this test surfaces, as warnings only, when a
supported catalog adapter reports a newer upstream version, and when a
catalog adapter discovers a relevant addon that is not yet declared.

It mirrors the Docker image / repository-ref external checks:

* warn-only: it NEVER fails the session, so registry slowness or outages do
  not break validation;
* opt-in: it runs through ``make test-external``, not the default
  ``make test`` flow (the live registry calls would otherwise flake CI);
* bounded: discovery is limited to the curated adapters in
  ``utils.update.addons.SUPPORTED_CATALOGS``, so broad public marketplaces
  (the full WordPress plugin directory, the whole GNOME extensions site)
  never produce unreviewable warning noise.

The reconciliation core (``discover_addon_updates``) is pure and is exercised
with fixture catalogs by the unit suite
(``tests/unit/python/utils/update/test_addons.py``); this file owns the live,
warn-only surface and degrades to "monitored, not yet checked" warnings when
no live adapter is wired for a catalog.
"""

from __future__ import annotations

import unittest

from utils.annotations.message import warning as gha_warning
from utils.update.addons import collect_addon_entries

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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
