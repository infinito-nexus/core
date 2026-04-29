from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from plugins.lookup.prometheus_integration_active import LookupModule
from utils.cache import _reset_cache_for_tests


def _make_applications(
    *app_ids: str,
    prometheus_deps: tuple = (),
) -> dict:
    """Build a minimal applications dict.

    Apps listed in *prometheus_deps* get services.prometheus.enabled: true.
    """
    apps = {}
    for app_id in app_ids:
        if app_id in prometheus_deps:
            apps[app_id] = {"services": {"prometheus": {"enabled": True}}}
        else:
            apps[app_id] = {}
    return apps


# Empty tmp roles dir → get_merged_applications returns the inventory
# `applications` override dict verbatim, without leaking real repo role defaults.
_TMP_ROLES_DIR_HOLDER: dict = {}


def setUpModule() -> None:
    _TMP_ROLES_DIR_HOLDER["tmpdir"] = tempfile.TemporaryDirectory()
    _TMP_ROLES_DIR_HOLDER["path"] = Path(_TMP_ROLES_DIR_HOLDER["tmpdir"].name)


def tearDownModule() -> None:
    _TMP_ROLES_DIR_HOLDER["tmpdir"].cleanup()


def _run(applications: dict, application_id: str, group_names: list) -> bool:
    _reset_cache_for_tests()
    return LookupModule().run(
        [],
        variables={
            "applications": applications,
            "application_id": application_id,
            "group_names": group_names,
        },
        roles_dir=str(_TMP_ROLES_DIR_HOLDER["path"]),
    )[0]


def _run_explicit(applications: dict, application_id: str, group_names: list) -> bool:
    """Invoke with application_id as explicit term 0 — the template usage pattern."""
    _reset_cache_for_tests()
    return LookupModule().run(
        [application_id],
        variables={
            "applications": applications,
            "group_names": group_names,
        },
        roles_dir=str(_TMP_ROLES_DIR_HOLDER["path"]),
    )[0]


class TestPrometheusIntegrationActiveDeploymentCheck(unittest.TestCase):
    """group_names gate — web-app-prometheus must be on this host."""

    def test_false_when_prometheus_not_in_group_names(self):
        apps = _make_applications("web-app-gitea", prometheus_deps=("web-app-gitea",))
        result = _run(apps, "web-app-gitea", [])
        self.assertFalse(result)

    def test_false_when_prometheus_not_deployed_even_with_dep(self):
        apps = _make_applications("web-app-gitea", prometheus_deps=("web-app-gitea",))
        result = _run(apps, "web-app-gitea", ["web-app-gitea"])
        self.assertFalse(result)


class TestPrometheusIntegrationActivePrometheusVhost(unittest.TestCase):
    """When the current app IS web-app-prometheus the result is always True."""

    def test_true_for_prometheus_vhost_itself(self):
        apps = _make_applications("web-app-prometheus")
        result = _run(apps, "web-app-prometheus", ["web-app-prometheus"])
        self.assertTrue(result)

    def test_true_for_prometheus_vhost_even_without_service_dep(self):
        # web-app-prometheus doesn't need its own service dep — it IS the host.
        apps = {"web-app-prometheus": {}}
        result = _run(apps, "web-app-prometheus", ["web-app-prometheus"])
        self.assertTrue(result)


class TestPrometheusIntegrationActiveServiceDep(unittest.TestCase):
    """services.prometheus.enabled gate for non-prometheus vhosts."""

    def test_true_when_app_declares_prometheus_dep(self):
        apps = _make_applications("web-app-gitea", prometheus_deps=("web-app-gitea",))
        result = _run(apps, "web-app-gitea", ["web-app-prometheus", "web-app-gitea"])
        self.assertTrue(result)

    def test_false_when_app_has_no_prometheus_dep(self):
        apps = _make_applications("web-app-gitea")
        result = _run(apps, "web-app-gitea", ["web-app-prometheus", "web-app-gitea"])
        self.assertFalse(result)

    def test_false_when_prometheus_dep_disabled(self):
        apps = {"web-app-gitea": {"services": {"prometheus": {"enabled": False}}}}
        result = _run(apps, "web-app-gitea", ["web-app-prometheus", "web-app-gitea"])
        self.assertFalse(result)


class TestPrometheusIntegrationActiveExplicitTerm(unittest.TestCase):
    """application_id passed as explicit term 0 — matches template invocation pattern.

    Templates call lookup('prometheus_integration_active', application_id).
    'applications' is read from available_variables.
    """

    def test_true_when_app_declares_prometheus_dep_explicit(self):
        apps = _make_applications("web-app-gitea", prometheus_deps=("web-app-gitea",))
        result = _run_explicit(
            apps, "web-app-gitea", ["web-app-prometheus", "web-app-gitea"]
        )
        self.assertTrue(result)

    def test_false_when_app_has_no_prometheus_dep_explicit(self):
        apps = _make_applications("web-app-gitea")
        result = _run_explicit(
            apps, "web-app-gitea", ["web-app-prometheus", "web-app-gitea"]
        )
        self.assertFalse(result)

    def test_true_for_prometheus_vhost_explicit(self):
        apps = _make_applications("web-app-prometheus")
        result = _run_explicit(apps, "web-app-prometheus", ["web-app-prometheus"])
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
