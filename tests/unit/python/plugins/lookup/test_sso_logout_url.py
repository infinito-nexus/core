import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError

from .test_sso import _apps, _load_module

KEYCLOAK_LOGOUT = "https://auth.example.org/realms/r/protocol/openid-connect/logout"
OIDC = {"CLIENT": {"LOGOUT_URL": KEYCLOAK_LOGOUT}}


class SsoLogoutUrlLookupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module("plugins/lookup/sso.py", "sso")

    def _run(self, applications, variables):
        lk = self.mod.LookupModule()
        lk._loader = mock.MagicMock()
        lk._templar = mock.MagicMock(template=lambda value: value)
        with mock.patch.object(self.mod, "lookup_loader") as loader_mock:
            loader_mock.get.return_value = mock.MagicMock(
                run=lambda *_a, **_k: [applications]
            )
            return lk.run(["web-app-x", "logout_url"], variables=variables)

    def test_a_proxy_gated_app_signs_out_of_oauth2_proxy_first(self):
        result = self._run(_apps(enabled=True, flavor="oauth2"), {"OIDC": OIDC})
        self.assertEqual(
            result,
            [
                "/oauth2/sign_out?rd=https%3A//auth.example.org/realms/r/protocol/openid-connect/logout"
            ],
        )

    def test_an_oidc_native_app_logs_out_at_the_provider(self):
        result = self._run(_apps(enabled=True, flavor="oidc"), {"OIDC": OIDC})
        self.assertEqual(result, [KEYCLOAK_LOGOUT])

    def test_a_disabled_sso_keeps_the_provider_logout(self):
        result = self._run(_apps(enabled=False, flavor="oauth2"), {"OIDC": OIDC})
        self.assertEqual(result, [KEYCLOAK_LOGOUT])

    def test_a_context_without_oidc_is_refused(self):
        with self.assertRaises(AnsibleError) as ctx:
            self._run(_apps(enabled=True, flavor="oauth2"), {"applications": {}})
        self.assertIn("OIDC", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
