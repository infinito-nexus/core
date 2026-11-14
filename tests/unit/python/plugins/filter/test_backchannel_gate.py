import unittest

from ansible.errors import AnsibleFilterError

from plugins.filter.backchannel_gate import logout_gate_apps


def gated(flag) -> dict:
    return {"services": {"sso": {"oidc": {"backchannel_logout_gate": flag}}}}


APPLICATIONS = {
    "web-app-zammad": gated(True),
    "web-app-xwiki": gated(True),
    "web-app-mediawiki": gated(True),
    "web-app-opencloud": gated(False),
    "web-app-matrix": {"services": {"sso": {"oidc": {}}}},
    "web-app-wordpress": {"services": {}},
}


class TestLogoutGateApps(unittest.TestCase):
    def test_only_deployed_apps_that_set_the_flag_are_returned_sorted(self) -> None:
        deployed = [
            "web-app-zammad",
            "web-app-xwiki",
            "web-app-opencloud",
            "web-app-matrix",
            "web-app-wordpress",
        ]
        self.assertEqual(
            logout_gate_apps(APPLICATIONS, deployed),
            ["web-app-xwiki", "web-app-zammad"],
        )

    def test_a_host_without_a_gated_app_gets_no_gate_client(self) -> None:
        self.assertEqual(logout_gate_apps(APPLICATIONS, ["web-app-matrix"]), [])

    def test_a_flag_that_is_no_boolean_fails_the_render(self) -> None:
        with self.assertRaises(AnsibleFilterError):
            logout_gate_apps({"web-app-xwiki": gated("maybe")}, ["web-app-xwiki"])


if __name__ == "__main__":
    unittest.main()
