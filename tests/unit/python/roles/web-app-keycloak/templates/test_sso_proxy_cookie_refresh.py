from __future__ import annotations

import re
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

TEMPLATE = "roles/web-app-keycloak/templates/sso_proxy/oauth2-proxy-keycloak.cfg.j2"
SERVICES = load_yaml(
    str(PROJECT_ROOT / "roles/web-app-keycloak" / ROLE_FILE_META_SERVICES)
)
OAUTH2_PROXY_DEFAULT_COOKIE_EXPIRE = "168h"
GO_DURATION = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?")


def _seconds(duration: str) -> int:
    match = GO_DURATION.fullmatch(duration)
    if not duration or match is None:
        raise ValueError(f"{duration!r} is not a Go duration of h, m and s")
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _lifetimes_not_outlived(cookie_refresh: str) -> list[str]:
    lifetimes = {
        "ssoSessionIdleTimeout": SERVICES["keycloak"]["realm"][
            "sso_session_idle_timeout_seconds"
        ],
        "cookie_expire": _seconds(OAUTH2_PROXY_DEFAULT_COOKIE_EXPIRE),
    }
    refresh = _seconds(cookie_refresh)
    return [name for name, seconds in lifetimes.items() if refresh >= seconds]


def _render(sso_proxy: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )

    def lookup(name: str, *terms, **_kwargs):
        if name == "config" and terms[0] == "web-app-keycloak":
            node = {"services": {"sso_proxy": sso_proxy}}
            for part in terms[1].split("."):
                node = node[part]
            return node
        if name == "config":
            return "cookie-secret"
        if name == "domains":
            return ["app.example.com"]
        if name == "tls":
            return True if terms[1] == "enabled" else "https"
        if name in ("sso_cookie_domains", "sso", "engine"):
            return ""
        if name == "sso_whitelist_domains":
            return []
        raise AssertionError(f"unexpected lookup {name}{terms}")

    env.globals["lookup"] = lookup
    env.filters["domain_strings"] = lambda domains: domains
    env.filters["in_network"] = lambda domains, _network: domains
    env.filters["to_json"] = str
    return env.get_template(TEMPLATE).render(
        sso_proxy_application_id="web-app-app",
        sso_proxy_network="clearnet",
        DOMAIN_PRIMARY="example.com",
    )


class TestSsoProxyCookieRefresh(unittest.TestCase):
    def test_the_config_renders_the_configured_cookie_refresh(self) -> None:
        rendered = _render({"cookie_refresh": "1m", "csrf_cookie_limit": 10})

        self.assertRegex(rendered, r'(?m)^cookie_refresh\s+=\s+"1m"$')

    def test_the_render_fails_without_the_key(self) -> None:
        with self.assertRaises(KeyError):
            _render({"csrf_cookie_limit": 10})

    def test_the_shipped_value_is_shorter_than_both_session_lifetimes(self) -> None:
        shipped = SERVICES["sso_proxy"]["cookie_refresh"]

        self.assertEqual(_lifetimes_not_outlived(shipped), [])

    def test_a_value_at_the_idle_timeout_fails_the_check(self) -> None:
        self.assertEqual(_lifetimes_not_outlived("30m"), ["ssoSessionIdleTimeout"])

    def test_a_value_that_is_no_go_duration_fails_the_check(self) -> None:
        with self.assertRaises(ValueError):
            _lifetimes_not_outlived("1d")


if __name__ == "__main__":
    unittest.main()
