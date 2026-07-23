import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import patch

from ansible.errors import AnsibleError

from . import PROJECT_ROOT


def _ensure_repo_root_on_syspath():
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))


_ensure_repo_root_on_syspath()

import plugins.lookup.asset as asset_mod  # noqa: E402
import plugins.lookup.asset_host as asset_host_mod  # noqa: E402


def _patched_loader(flavor="internal", domain="cdn.example.org"):
    """Patch context for the asset module's lookup_loader.

    Args:
        flavor: value the mocked `config` lookup returns for services.cdn.flavor.
        domain: value the mocked `domain` lookup returns for web-svc-cdn.
    """

    def _get(name, *a, **k):
        if name == "config":
            return mock.MagicMock(run=lambda *_a, **_k: [flavor])
        if name == "domain":
            return mock.MagicMock(run=lambda *_a, **_k: [domain])
        return mock.MagicMock(run=lambda *_a, **_k: [{}])

    loader_mock = mock.MagicMock()
    loader_mock.get.side_effect = _get
    return patch.object(asset_mod, "lookup_loader", loader_mock)


def _write_lock(tmpdir: str, packages: dict) -> None:
    lock = {
        "lockfileVersion": 3,
        "packages": {
            f"node_modules/{name}": {"version": version}
            for name, version in packages.items()
        },
    }
    files_dir = Path(tmpdir, "files")
    files_dir.mkdir(exist_ok=True)
    (files_dir / "package-lock.json").write_text(json.dumps(lock))


class TestResolveHost(unittest.TestCase):
    """Branch logic of resolve_host, shared by the asset and asset_host lookups."""

    def test_without_cdn_group_returns_jsdelivr(self):
        with _patched_loader():
            host = asset_mod.resolve_host({"group_names": ["web-app-kix"]}, None, None)
        self.assertEqual(host, "https://cdn.jsdelivr.net")

    def test_internal_flavor_returns_cdn_domain(self):
        with _patched_loader(flavor="internal"):
            host = asset_mod.resolve_host({"group_names": ["web-svc-cdn"]}, None, None)
        self.assertEqual(host, "https://cdn.example.org")

    def test_external_flavor_returns_jsdelivr(self):
        with _patched_loader(flavor="external"):
            host = asset_mod.resolve_host({"group_names": ["web-svc-cdn"]}, None, None)
        self.assertEqual(host, "https://cdn.jsdelivr.net")

    def test_missing_group_names_returns_jsdelivr(self):
        with _patched_loader():
            host = asset_mod.resolve_host({}, None, None)
        self.assertEqual(host, "https://cdn.jsdelivr.net")


class TestLockedVersion(unittest.TestCase):
    """package-lock.json parsing incl. scoped packages and both error paths."""

    def setUp(self):
        self.lookup = asset_mod.LookupModule.__new__(asset_mod.LookupModule)
        self.tmpdir = tempfile.mkdtemp()

    def _patched_role_path(self):
        return patch.object(
            asset_mod, "abs_role_path_by_application_id", return_value=self.tmpdir
        )

    def test_plain_package(self):
        _write_lock(self.tmpdir, {"keycloak-js": "24.0.5"})
        with self._patched_role_path():
            self.assertEqual(
                self.lookup._locked_version("app", "keycloak-js"), "24.0.5"
            )

    def test_scoped_package(self):
        _write_lock(self.tmpdir, {"@fortawesome/fontawesome-free": "6.5.1"})
        with self._patched_role_path():
            self.assertEqual(
                self.lookup._locked_version("app", "@fortawesome/fontawesome-free"),
                "6.5.1",
            )

    def test_missing_package_raises(self):
        _write_lock(self.tmpdir, {"bootstrap": "5.3.3"})
        with self._patched_role_path(), self.assertRaises(AnsibleError):
            self.lookup._locked_version("app", "not-a-package")

    def test_missing_lockfile_raises(self):
        with self._patched_role_path(), self.assertRaises(AnsibleError):
            self.lookup._locked_version("app", "bootstrap")


class TestAssetRun(unittest.TestCase):
    """URL assembly of the full lookup('asset', app, package, path) call."""

    def setUp(self):
        self.lookup = asset_mod.LookupModule.__new__(asset_mod.LookupModule)
        self.lookup._loader = mock.MagicMock()
        self.lookup._templar = mock.MagicMock(available_variables={})
        self.tmpdir = tempfile.mkdtemp()
        _write_lock(self.tmpdir, {"bootstrap": "5.3.3"})

    def _run(self, terms, variables):
        with (
            patch.object(
                asset_mod, "abs_role_path_by_application_id", return_value=self.tmpdir
            ),
            _patched_loader(flavor="internal"),
        ):
            return self.lookup.run(terms, variables=variables)

    def test_internal_url(self):
        result = self._run(
            ["app", "bootstrap", "dist/css/bootstrap.min.css"],
            {"group_names": ["web-svc-cdn"]},
        )
        self.assertEqual(
            result,
            ["https://cdn.example.org/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"],
        )

    def test_external_url(self):
        result = self._run(
            ["app", "bootstrap", "dist/js/bootstrap.bundle.min.js"],
            {"group_names": ["web-app-kix"]},
        )
        self.assertEqual(
            result,
            [
                (
                    "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3"
                    "/dist/js/bootstrap.bundle.min.js"
                )
            ],
        )

    def test_leading_slash_path_is_normalized(self):
        result = self._run(
            ["app", "bootstrap", "/dist/css/bootstrap.min.css"],
            {"group_names": []},
        )
        self.assertEqual(
            result,
            ["https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"],
        )

    def test_wrong_term_count_raises(self):
        with self.assertRaises(AnsibleError):
            self._run(["app", "bootstrap"], {"group_names": []})


class TestAssetHostRun(unittest.TestCase):
    """asset_host must return exactly the resolve_host origin (CSP source)."""

    def test_matches_resolve_host(self):
        lookup = asset_host_mod.LookupModule.__new__(asset_host_mod.LookupModule)
        lookup._loader = mock.MagicMock()
        lookup._templar = mock.MagicMock(available_variables={})
        with _patched_loader(flavor="internal"):
            result = lookup.run([], variables={"group_names": ["web-svc-cdn"]})
        self.assertEqual(result, ["https://cdn.example.org"])


class TestCommittedRoleLockfiles(unittest.TestCase):
    """The real committed role lockfiles must satisfy the lookup, so a deploy
    templating dashboard/littlejs never dies on a malformed or v1-format lock."""

    URL_RE = re.compile(r"^https://cdn\.jsdelivr\.net/npm/.+@\d[^/]*/.+$")

    def _url(self, app, package, path):
        lookup = asset_mod.LookupModule.__new__(asset_mod.LookupModule)
        lookup._loader = mock.MagicMock()
        lookup._templar = mock.MagicMock(available_variables={})
        with _patched_loader():
            return lookup.run([app, package, path], variables={"group_names": []})[0]

    def test_dashboard_keycloak_js(self):
        url = self._url("web-app-dashboard", "keycloak-js", "dist/keycloak.js")
        self.assertRegex(url, self.URL_RE)

    def test_littlejs_bootstrap(self):
        url = self._url("web-app-littlejs", "bootstrap", "dist/css/bootstrap.min.css")
        self.assertRegex(url, self.URL_RE)

    def test_littlejs_fontawesome(self):
        url = self._url(
            "web-app-littlejs", "@fortawesome/fontawesome-free", "css/all.min.css"
        )
        self.assertRegex(url, self.URL_RE)


if __name__ == "__main__":
    unittest.main()
