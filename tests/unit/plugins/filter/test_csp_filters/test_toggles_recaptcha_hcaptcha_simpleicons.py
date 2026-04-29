import unittest
import copy
from plugins.filter.csp_filters import FilterModule


class TestCspTogglesRecaptchaHcaptchaCss(unittest.TestCase):
    def setUp(self):
        self.filter = FilterModule()
        self.apps = {
            "app1": {
                "docker": {"services": {"matomo": {"enabled": False}}},
                "server": {"csp": {"whitelist": {}, "flags": {}, "hashes": {}}},
            }
        }
        self.domains = {
            "web-svc-cdn": ["cdn.example.org"],
            "web-svc-simpleicons": ["simpleicons.example.org"],
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

    def test_recaptcha_toggle(self):
        apps = copy.deepcopy(self.apps)

        self._set_service_enabled(apps, "recaptcha", True)
        header_enabled = self.filter.build_csp_header(
            apps, "app1", self.domains, "https"
        )
        self.assertIn("https://www.google.com", header_enabled)

        self._set_service_enabled(apps, "recaptcha", False)
        header_disabled = self.filter.build_csp_header(
            apps, "app1", self.domains, "https"
        )
        self.assertNotIn("https://www.google.com", header_disabled)

    def test_hcaptcha_toggle(self):
        apps = copy.deepcopy(self.apps)

        self._set_service_enabled(apps, "hcaptcha", True)
        header_enabled = self.filter.build_csp_header(
            apps, "app1", self.domains, "https"
        )

        script_elem = self._get_directive_tokens(header_enabled, "script-src-elem")
        self.assertIn("https://www.hcaptcha.com", script_elem)
        self.assertIn("https://js.hcaptcha.com", script_elem)

        script_base = self._get_directive_tokens(header_enabled, "script-src")
        self.assertIn("https://www.hcaptcha.com", script_base)
        self.assertIn("https://js.hcaptcha.com", script_base)

        frame = self._get_directive_tokens(header_enabled, "frame-src")
        self.assertIn("https://newassets.hcaptcha.com/", frame)

        self._set_service_enabled(apps, "hcaptcha", False)
        header_disabled = self.filter.build_csp_header(
            apps, "app1", self.domains, "https"
        )
        for d in ("script-src", "script-src-elem", "frame-src"):
            toks = self._get_directive_tokens(header_disabled, d)
            self.assertNotIn("https://www.hcaptcha.com", toks)
            self.assertNotIn("https://js.hcaptcha.com", toks)
            self.assertNotIn("https://newassets.hcaptcha.com/", toks)

    def test_simpleicons_toggle_affects_connect_src(self):
        apps = copy.deepcopy(self.apps)

        self._set_service_enabled(apps, "simpleicons", True)
        header_enabled = self.filter.build_csp_header(
            apps, "app1", self.domains, "https"
        )
        connect_tokens = self._get_directive_tokens(header_enabled, "connect-src")
        self.assertIn("https://simpleicons.example.org", connect_tokens)

        self._set_service_enabled(apps, "simpleicons", False)
        header_disabled = self.filter.build_csp_header(
            apps, "app1", self.domains, "https"
        )
        connect_tokens_disabled = self._get_directive_tokens(
            header_disabled, "connect-src"
        )
        self.assertNotIn("https://simpleicons.example.org", connect_tokens_disabled)


if __name__ == "__main__":
    unittest.main()
