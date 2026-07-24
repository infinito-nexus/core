import importlib
import importlib.util
import sys
import unittest
from unittest import mock

from ansible.errors import AnsibleError

from . import PROJECT_ROOT


def _load_module(rel_path: str, name: str):
    # Evict any stubbed utils.roles.applications.config injected by sibling tests
    # (notably tests/unit/roles/web-app-keycloak/filter_plugins/test_redirect_uris.py,
    # whose setUpClass registers a stub `get()` with an incompatible signature
    # into sys.modules and never cleans up). Force the plugin to import the
    # real module from the repo.
    for key in (
        "utils.roles.applications.config",
        "utils.roles.applications",
        "utils",
        "utils.cache.applications",
        "utils.cache",
    ):
        sys.modules.pop(key, None)
    importlib.import_module("utils.roles.applications.config")
    importlib.import_module("utils.cache.applications")

    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _apps(*, oidc_enabled=True, ldap_enabled=None, flavor=None, include_app=True):
    """Build a minimal merged `applications` dict for the Nextcloud role.

    `oidc_enabled` defaults to True so existing flavor-selection tests
    stay focused on the ldap/flavor axis. The OIDC-off fast-path has
    its own dedicated tests.
    """
    if not include_app:
        return {}
    # `flavor=` here parameterises the Nextcloud-specific sub-flavor that
    # is now services.sso.oidc.plugin (was renamed from the legacy path
    # per the SSO flavor migration).
    sso_block: dict = {"enabled": oidc_enabled}
    if flavor is not None:
        sso_block["oidc"] = {"plugin": flavor}
    services_block: dict = {"sso": sso_block}
    if ldap_enabled is not None:
        services_block["ldap"] = {"enabled": ldap_enabled}
    # Per the materialised payload moved from
    # `applications.<app>.compose.services.<X>` to `applications.<app>.services.<X>`.
    return {
        "web-app-nextcloud": {
            "services": services_block,
        },
    }


class OidcFlavorLookupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module(
            "plugins/lookup/sso_oidc_plugin.py",
            "sso_oidc_plugin",
        )

    def setUp(self):
        # Stub the applications lookup so tests inject the merged view directly
        # instead of round-tripping through the filesystem role config scan.
        self._patcher = mock.patch.object(self.mod, "lookup_loader")
        self._loader_mock = self._patcher.start()
        self._stub_payload = None
        self._loader_mock.get.return_value = mock.MagicMock(
            run=lambda *_a, **_k: [self._stub_payload]
        )

    def tearDown(self):
        self._patcher.stop()

    def _run(self, applications, *, terms=None):
        self._stub_payload = applications
        lk = self.mod.LookupModule()
        lk._loader = mock.MagicMock()
        return lk.run(terms or [], variables={"applications": applications})

    def test_ldap_enabled_returns_oidc_login(self):
        self.assertEqual(
            self._run(_apps(ldap_enabled=True)),
            ["oidc_login"],
        )

    def test_ldap_disabled_returns_sociallogin(self):
        self.assertEqual(
            self._run(_apps(ldap_enabled=False)),
            ["sociallogin"],
        )

    def test_ldap_missing_defaults_to_sociallogin(self):
        self.assertEqual(
            self._run(_apps()),
            ["sociallogin"],
        )

    def test_missing_application_returns_empty(self):
        # No nextcloud entry -> services.sso.enabled defaults False ->
        # short-circuit to "" (no OIDC plugin should be active).
        self.assertEqual(
            self._run({"some-other-app": {}}),
            [""],
        )

    def test_oidc_disabled_returns_empty(self):
        # With services.sso.enabled=false, no OIDC plugin must be selected,
        # otherwise Nextcloud still hands off to Keycloak with a redirect_uri
        # the client no longer whitelists. Regression test for variant-1
        # nextcloud Playwright failures ("Invalid parameter: redirect_uri").
        self.assertEqual(
            self._run(_apps(oidc_enabled=False)),
            [""],
        )
        self.assertEqual(
            self._run(_apps(oidc_enabled=False, ldap_enabled=True)),
            [""],
        )
        self.assertEqual(
            self._run(_apps(oidc_enabled=False, flavor="oidc_login")),
            [""],
        )

    def test_explicit_flavor_overrides_ldap_fallback(self):
        self.assertEqual(
            self._run(_apps(ldap_enabled=True, flavor="sociallogin")),
            ["sociallogin"],
        )
        self.assertEqual(
            self._run(_apps(ldap_enabled=False, flavor="user_oidc")),
            ["user_oidc"],
        )

    def test_explicit_flavor_is_stripped(self):
        self.assertEqual(
            self._run(_apps(ldap_enabled=False, flavor="  oidc_login  ")),
            ["oidc_login"],
        )

    def test_blank_explicit_flavor_falls_back_to_ternary(self):
        self.assertEqual(
            self._run(_apps(ldap_enabled=True, flavor="   ")),
            ["oidc_login"],
        )
        self.assertEqual(
            self._run(_apps(ldap_enabled=False, flavor="")),
            ["sociallogin"],
        )

    def test_null_explicit_flavor_falls_back_to_ternary(self):
        self.assertEqual(
            self._run(_apps(ldap_enabled=True, flavor=None)),
            ["oidc_login"],
        )

    def test_non_string_explicit_flavor_is_ignored(self):
        self.assertEqual(
            self._run(_apps(ldap_enabled=True, flavor=42)),
            ["oidc_login"],
        )

    def test_rejects_positional_terms(self):
        lk = self.mod.LookupModule()
        with self.assertRaises(AnsibleError):
            lk.run(["unexpected"], variables={"applications": _apps()})


if __name__ == "__main__":
    unittest.main()
