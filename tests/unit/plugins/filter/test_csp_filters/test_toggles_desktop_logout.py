import unittest
import copy
from plugins.filter.csp_filters import FilterModule


class TestCspTogglesDashboardLogout(unittest.TestCase):
    def setUp(self):
        self.filter = FilterModule()
        self.apps = {
            "app1": {
                "services": {"matomo": {"enabled": False}},
                "server": {"csp": {"whitelist": {}, "flags": {}, "hashes": {}}},
            }
        }
        self.domains = {
            "web-svc-cdn": ["cdn.example.org"],
            "web-app-keycloak": ["keycloak.example.org"],
            "web-svc-logout": ["logout.example.org"],
        }

    def _get_directive_tokens(self, header: str, directive: str):
        for part in header.split(";"):
            part = part.strip()
            if part.startswith(directive + " "):
                remainder = part[len(directive) :].strip()
                return [tok for tok in remainder.split(" ") if tok]
        return []

    def _set_service_enabled(self, apps: dict, service: str, enabled: bool):
        # Per req-008 the materialised payload moved to services.<X>.
        apps["app1"].setdefault("services", {}).setdefault(service, {})
        apps["app1"]["services"][service]["enabled"] = enabled

    def test_frame_ancestors_dashboard_toggle(self):
        apps = copy.deepcopy(self.apps)
        domains = copy.deepcopy(self.domains)
        domains["web-app-dashboard"] = ["domain-example.com"]

        self._set_service_enabled(apps, "dashboard", True)
        header = self.filter.build_csp_header(apps, "app1", domains, "https")
        self.assertIn("frame-ancestors", header)
        frame_ancestors = self._get_directive_tokens(header, "frame-ancestors")
        self.assertIn("domain-example.com", frame_ancestors)
        self.assertNotIn("https://domain-example.com", frame_ancestors)

        self._set_service_enabled(apps, "dashboard", False)
        header_no = self.filter.build_csp_header(apps, "app1", domains, "https")
        self.assertNotIn("domain-example.com", header_no)

    def test_logout_disabled_does_not_add_unsafe_inline(self):
        apps = copy.deepcopy(self.apps)
        self._set_service_enabled(apps, "logout", False)

        header = self.filter.build_csp_header(apps, "app1", self.domains, "https")
        self.assertNotIn(
            "'unsafe-inline'", self._get_directive_tokens(header, "script-src-attr")
        )
        self.assertNotIn(
            "'unsafe-inline'", self._get_directive_tokens(header, "script-src-elem")
        )

    def test_logout_enabled_adds_unsafe_inline_attr_and_elem(self):
        apps = copy.deepcopy(self.apps)
        self._set_service_enabled(apps, "logout", True)

        header = self.filter.build_csp_header(apps, "app1", self.domains, "https")
        self.assertIn(
            "'unsafe-inline'", self._get_directive_tokens(header, "script-src-attr")
        )
        self.assertIn(
            "'unsafe-inline'", self._get_directive_tokens(header, "script-src-elem")
        )

    def test_logout_respects_explicit_disable_on_base_script_src(self):
        apps = copy.deepcopy(self.apps)
        apps["app1"].setdefault("server", {}).setdefault("csp", {}).setdefault(
            "flags", {}
        )
        apps["app1"]["server"]["csp"]["flags"]["script-src"] = {
            "unsafe-inline": False,
            "unsafe-eval": True,
        }
        self._set_service_enabled(apps, "logout", True)

        header = self.filter.build_csp_header(apps, "app1", self.domains, "https")
        base = self._get_directive_tokens(header, "script-src")
        attr = self._get_directive_tokens(header, "script-src-attr")
        elem = self._get_directive_tokens(header, "script-src-elem")

        self.assertNotIn("'unsafe-inline'", base)
        self.assertIn("'unsafe-inline'", attr)
        self.assertIn("'unsafe-inline'", elem)

    def test_logout_propagates_to_base_when_not_explicitly_disabled(self):
        apps = copy.deepcopy(self.apps)
        apps["app1"].setdefault("server", {}).setdefault("csp", {}).setdefault(
            "flags", {}
        )
        apps["app1"]["server"]["csp"]["flags"]["script-src"] = {"unsafe-eval": True}
        self._set_service_enabled(apps, "logout", True)

        header = self.filter.build_csp_header(apps, "app1", self.domains, "https")
        base = self._get_directive_tokens(header, "script-src")
        self.assertIn("'unsafe-inline'", base)


if __name__ == "__main__":
    unittest.main()
