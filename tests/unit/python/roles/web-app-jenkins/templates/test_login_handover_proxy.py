from __future__ import annotations

import re
import unittest

from jinja2 import (
    ChoiceLoader,
    DictLoader,
    Environment,
    FileSystemLoader,
    StrictUndefined,
    select_autoescape,
)

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVER

from . import PROJECT_ROOT

ROLE = "web-app-jenkins"
ROLE_DIR = PROJECT_ROOT / "roles" / ROLE
METRICS_PATH = "/prometheus"
HANDOVER = "return 302 /securityRealm/commenceLogin$is_args$args;"
CONFIG = {
    "addons.prometheus.config.metrics_path": METRICS_PATH,
    "server.client_max_body_size": "100m",
}
STUBBED_INCLUDES = {
    "roles/sys-svc-proxy/templates/headers/identity_request_strips.conf.j2": "IDENTITY_STRIPS;\n",
    "roles/sys-svc-proxy/templates/headers/content_security_policy.conf.j2": "SECURITY_HEADERS;\n",
    "roles/sys-svc-proxy/templates/headers/access_control_allow.conf.j2": "ACCESS_CONTROL;\n",
    "roles/sys-svc-proxy/templates/headers/forwarded.conf.j2": "FORWARDED;\n",
    "roles/sys-svc-proxy/templates/headers/upstream_strips.conf.j2": "UPSTREAM_STRIPS;\n",
    "roles/sys-front-inj-all/templates/location.lua.j2": "LUA_INJECTION;\n",
}


def _lookup(kind: str, *args: object, **_kwargs: object) -> object:
    if kind == "proxy_pass":
        return "proxy_pass http://jenkins;"
    if kind == "config" and args[1] in CONFIG:
        return CONFIG[args[1]]
    raise AssertionError(f"unexpected lookup({kind!r}, {args!r})")


def render(sso: bool) -> str:
    """
    Args:
        sso: the role's ``JENKINS_OIDC_ENABLED``.

    Returns:
        The vhost extra the role's ``meta/server.yml`` hands svc-stack.
    """
    extra = load_yaml_any(str(ROLE_DIR / ROLE_FILE_META_SERVER))["vhosts"]["default"][
        "extra_template"
    ]
    environment = Environment(
        loader=ChoiceLoader(
            [DictLoader(STUBBED_INCLUDES), FileSystemLoader(str(PROJECT_ROOT))]
        ),
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
        trim_blocks=True,
        keep_trailing_newline=True,
    )
    environment.filters["bool"] = bool
    environment.filters["entity_name"] = lambda value: value.rsplit("-", 1)[-1]
    return environment.get_template(f"roles/{ROLE}/templates/{extra}").render(
        application_id=ROLE,
        JENKINS_OIDC_ENABLED=sso,
        http_port=8070,
        proxy_service_key="jenkins",
        lookup=_lookup,
    )


def location(rendered: str, matcher: str) -> list[str] | None:
    """
    Args:
        rendered: an nginx fragment.
        matcher: a location matcher, modifier included.

    Returns:
        The stripped lines of that location's body, or None without one.
    """
    found = re.search(
        rf"^location\s+{re.escape(matcher)}\s*\{{((?:[^{{}}]|\{{[^{{}}]*\}})*)\}}",
        rendered,
        re.MULTILINE,
    )
    if found is None:
        return None
    return [line.strip() for line in found.group(1).splitlines() if line.strip()]


class TestLoginHandsOverToTheOicRealm(unittest.TestCase):
    def test_sso_sends_login_to_the_oic_realm_with_its_query(self) -> None:
        body = location(render(sso=True), "= /login")
        self.assertIsNotNone(body, "the oic realm needs /login answered at the proxy")
        self.assertIn(HANDOVER, body)
        for kept in ("IDENTITY_STRIPS;", "SECURITY_HEADERS;", "FORWARDED;"):
            self.assertIn(kept, body)
        self.assertNotIn("LUA_INJECTION;", body)

    def test_without_sso_jenkins_serves_its_own_login(self) -> None:
        self.assertIsNone(location(render(sso=False), "= /login"))

    def test_metrics_stay_denied_in_both_modes(self) -> None:
        for sso in (True, False):
            with self.subTest(sso=sso):
                self.assertEqual(
                    ["deny all;"], location(render(sso=sso), f"= {METRICS_PATH}")
                )


if __name__ == "__main__":
    unittest.main()
