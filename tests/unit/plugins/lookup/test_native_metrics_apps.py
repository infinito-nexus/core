from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plugins.lookup.native_metrics_apps import LookupModule


def _run(applications: dict, roles_dir: Path, group_names: list | None = None) -> list:
    """Helper: run the lookup with a temporary roles directory.

    group_names defaults to all keys in applications so existing tests that
    don't care about the deployment filter still pass without change.
    """
    if group_names is None:
        group_names = list(applications.keys())
    with patch.object(LookupModule, "_find_roles_dir", return_value=roles_dir):
        return LookupModule().run(
            [],
            variables={"applications": applications, "group_names": group_names},
        )[0]


def _make_roles(tmp: Path, specs: dict) -> dict:
    """Create minimal role fixtures under tmp/ and return an applications dict.

    In real Ansible, role config/main.yml defaults are merged into the
    `applications` variable before any play runs. This helper replicates that
    by building both the filesystem structure (for fragment discovery) and the
    applications dict (for get_app_conf lookups) from the same spec.

    specs: { app_id: {"native_metrics_enabled": bool, "has_fragment": bool} }
    Returns: applications dict ready to pass to the lookup.
    """
    applications = {}
    for app_id, cfg in specs.items():
        # Filesystem: only the scrape fragment is needed on disk.
        # (config/main.yml is irrelevant here — data comes from applications dict.)
        if cfg.get("has_fragment"):
            tpl_dir = tmp / app_id / "templates"
            tpl_dir.mkdir(parents=True)
            (tpl_dir / "prometheus.yml.j2").write_text(f'  - job_name: "{app_id}"\n')
        # applications dict: mirrors what Ansible populates from role config defaults.
        # Per req-008 the materialised payload moved from
        # `applications.<app>.compose.services.<X>` to `applications.<app>.services.<X>`.
        applications[app_id] = {
            "services": {
                "prometheus": {
                    "native_metrics": {
                        "enabled": bool(cfg.get("native_metrics_enabled"))
                    }
                }
            }
        }
    return applications


class TestNativeMetricsApps(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.roles_dir = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    # ── basic inclusion ────────────────────────────────────────────────────

    def test_returns_app_with_enabled_and_fragment(self):
        apps = _make_roles(
            self.roles_dir,
            {
                "web-app-gitea": {"native_metrics_enabled": True, "has_fragment": True},
            },
        )
        self.assertEqual(_run(apps, self.roles_dir), ["web-app-gitea"])

    def test_excludes_app_without_native_metrics_enabled(self):
        apps = _make_roles(
            self.roles_dir,
            {
                "web-app-foo": {"native_metrics_enabled": False, "has_fragment": True},
            },
        )
        self.assertEqual(_run(apps, self.roles_dir), [])

    def test_excludes_app_without_scrape_fragment(self):
        apps = _make_roles(
            self.roles_dir,
            {
                "web-app-bar": {"native_metrics_enabled": True, "has_fragment": False},
            },
        )
        self.assertEqual(_run(apps, self.roles_dir), [])

    def test_excludes_app_not_in_applications(self):
        """Apps with a fragment but not deployed must be excluded."""
        _make_roles(
            self.roles_dir,
            {
                "web-app-gitea": {"native_metrics_enabled": True, "has_fragment": True},
            },
        )
        self.assertEqual(_run({}, self.roles_dir), [])

    # ── ordering ───────────────────────────────────────────────────────────

    def test_result_is_sorted(self):
        apps = _make_roles(
            self.roles_dir,
            {
                "web-app-zzz": {"native_metrics_enabled": True, "has_fragment": True},
                "web-app-aaa": {"native_metrics_enabled": True, "has_fragment": True},
                "web-app-mmm": {"native_metrics_enabled": True, "has_fragment": True},
            },
        )
        self.assertEqual(
            _run(apps, self.roles_dir), ["web-app-aaa", "web-app-mmm", "web-app-zzz"]
        )

    # ── multiple apps mixed ────────────────────────────────────────────────

    def test_returns_only_qualifying_apps(self):
        apps = _make_roles(
            self.roles_dir,
            {
                "web-app-gitea": {"native_metrics_enabled": True, "has_fragment": True},
                "web-app-mattermost": {
                    "native_metrics_enabled": True,
                    "has_fragment": True,
                },
                "web-app-matrix": {
                    "native_metrics_enabled": True,
                    "has_fragment": True,
                },
                "web-app-nofrag": {
                    "native_metrics_enabled": True,
                    "has_fragment": False,
                },
                "web-app-disabled": {
                    "native_metrics_enabled": False,
                    "has_fragment": True,
                },
            },
        )
        self.assertEqual(
            _run(apps, self.roles_dir),
            ["web-app-gitea", "web-app-matrix", "web-app-mattermost"],
        )

    # ── group_names deployment filter ──────────────────────────────────────

    def test_excludes_app_not_in_group_names(self):
        """Apps not in group_names (not deployed on this host) must be excluded."""
        apps = _make_roles(
            self.roles_dir,
            {
                "web-app-gitea": {"native_metrics_enabled": True, "has_fragment": True},
                "web-app-mattermost": {
                    "native_metrics_enabled": True,
                    "has_fragment": True,
                },
            },
        )
        result = _run(apps, self.roles_dir, group_names=["web-app-gitea"])
        self.assertIn("web-app-gitea", result)
        self.assertNotIn("web-app-mattermost", result)

    def test_returns_empty_when_group_names_empty(self):
        apps = _make_roles(
            self.roles_dir,
            {"web-app-gitea": {"native_metrics_enabled": True, "has_fragment": True}},
        )
        self.assertEqual(_run(apps, self.roles_dir, group_names=[]), [])


if __name__ == "__main__":
    unittest.main()
