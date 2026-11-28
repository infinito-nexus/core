import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError

from plugins.lookup.login_method import LookupModule

APPLICATIONS = {
    "web-app-both": {
        "services": {"sso": {"enabled": "True"}, "ldap": {"enabled": "True"}}
    },
    "web-app-directory": {
        "services": {"sso": {"enabled": False}, "ldap": {"enabled": "true"}}
    },
    "web-app-plain": {"services": {"sso": {"enabled": False}}},
}


class _Config:
    def run(self, terms, variables=None):
        node = APPLICATIONS[terms[0]]
        for key in terms[1].split("."):
            if key not in node:
                if len(terms) == 3:
                    return [terms[2]]
                raise KeyError(terms[1])
            node = node[key]
        return [node]


def _lookup(application_id, method):
    module = LookupModule()
    module._templar = None
    module._loader = None
    with mock.patch(
        "plugins.lookup.login_method.lookup_loader.get", return_value=_Config()
    ):
        return module.run([application_id, method], variables={})[0]


class TestLoginMethodLookup(unittest.TestCase):
    def test_sso_hides_ldap_and_native(self):
        self.assertTrue(_lookup("web-app-both", "sso"))
        self.assertFalse(_lookup("web-app-both", "ldap"))
        self.assertFalse(_lookup("web-app-both", "native"))
        self.assertFalse(_lookup("web-app-both", "2fa"))

    def test_ldap_without_sso_offers_ldap_and_second_factor(self):
        self.assertTrue(_lookup("web-app-directory", "ldap"))
        self.assertTrue(_lookup("web-app-directory", "2fa"))
        self.assertFalse(_lookup("web-app-directory", "native"))

    def test_an_app_without_ldap_service_signs_in_natively(self):
        self.assertTrue(_lookup("web-app-plain", "native"))
        self.assertFalse(_lookup("web-app-plain", "ldap"))

    def test_extras_stay_off(self):
        for method in ("passkey", "registration", "odoo_com"):
            with self.subTest(method=method):
                self.assertFalse(_lookup("web-app-plain", method))

    def test_an_unknown_method_raises(self):
        with self.assertRaises(AnsibleError):
            _lookup("web-app-plain", "magic")


if __name__ == "__main__":
    unittest.main()
