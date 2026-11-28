from __future__ import annotations

import unittest

from plugins.filter.csp_filters import FilterModule
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_CSP, ROLE_FILE_META_VARIANTS

APPLICATION_ID = "web-app-checkmk"
ROLE = PROJECT_ROOT / "roles" / APPLICATION_ID
DOMAINS = {
    APPLICATION_ID: ["monitoring.example.org"],
    "web-svc-cdn": ["cdn.example.org"],
    "web-svc-logout": ["logout.example.org"],
    "web-app-keycloak": ["auth.example.org"],
}


def _variants() -> list[dict]:
    return load_yaml_str(read_text(str(ROLE / ROLE_FILE_META_VARIANTS)))


def _tokens(logout_enabled: bool, directive: str) -> list[str]:
    applications = {
        APPLICATION_ID: {
            "csp": load_yaml_str(read_text(str(ROLE / ROLE_FILE_META_CSP))),
            "services": {"logout": {"enabled": logout_enabled}},
        }
    }
    header = FilterModule().build_csp_header(
        applications, APPLICATION_ID, DOMAINS, "https"
    )
    for raw in header.split(";"):
        name, _, tokens = raw.strip().partition(" ")
        if name == directive:
            return tokens.split()
    raise AssertionError(f"no {directive} in {header!r}")


class TestCheckmkCsp(unittest.TestCase):
    def test_every_variant_runs_the_inline_event_handlers_of_the_gui(self) -> None:
        for index, variant in enumerate(_variants()):
            logout_enabled = variant["services"]["logout"]["enabled"]
            with self.subTest(variant=index, logout=logout_enabled):
                self.assertIn(
                    "'unsafe-inline'",
                    _tokens(logout_enabled, "script-src-attr"),
                    "Checkmk opens its Monitor, Customize, Setup, Help and User "
                    "menus through inline onclick attributes, so script-src-attr "
                    "MUST admit them on every vhost, not only where the logout "
                    "injector happens to grant it",
                )


if __name__ == "__main__":
    unittest.main()
