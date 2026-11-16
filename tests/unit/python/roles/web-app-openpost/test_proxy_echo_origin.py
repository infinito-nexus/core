from __future__ import annotations

import re
import unittest
from urllib.parse import urlsplit

from jinja2 import (
    ChoiceLoader,
    DictLoader,
    Environment,
    FileSystemLoader,
    StrictUndefined,
    select_autoescape,
)

from utils.cache.files import PROJECT_ROOT

PROXY_TEMPLATE = "roles/web-app-openpost/templates/proxy.conf.j2"
DOMAIN = "publish.example.test"
LOCATION_STUB = "LOCATION[{{ location }}]PROTO[{{ proxy_x_forwarded_proto | default('$scheme') }}]EXTRA[{{ webserver_location_extra_configuration | default('') }}]END"
STUBS = {
    "roles/sys-svc-proxy/templates/cdn.conf.j2": "",
    "roles/sys-svc-proxy/templates/headers/buffers.conf.j2": "",
    "roles/web-app-keycloak/templates/sso_proxy/endpoint.conf.j2": "",
    "roles/sys-front-inj-all/templates/server.conf.j2": "",
    "roles/sys-front-tls/templates/nginx_ssl_header.j2": "",
    "roles/sys-svc-proxy/templates/location/handover.conf.j2": "HANDOVER",
    "roles/sys-svc-proxy/templates/location/sso_acl.conf.j2": "SSO_ACL",
    "roles/sys-svc-proxy/templates/location/html.conf.j2": LOCATION_STUB,
    "roles/web-app-prometheus/templates/nginx/locations.conf.j2": "",
    "roles/web-svc-seaweedfs/templates/nginx/locations.conf.j2": "",
    "roles/sys-svc-proxy/templates/mcp/vhost.conf.j2": "",
}
ECHO_ROUTES = (
    "/api/v1/media/upload",
    "/api/v1/media/batch-upload",
    "/api/v1/media/metadata",
    "/api/v1/media/upload-session/0b6f/content",
    "/api/v1/auth/profile/avatar",
    "/api/v1/admin/backup",
    "/api/v1/admin/backup/restore/upload",
    "/api/v1/admin/backup/restore-points/nightly",
)
HUMA_ROUTES = (
    "/api/v1/media/upload-session",
    "/api/v1/media/upload-session/0b6f/complete",
    "/api/v1/media",
    "/api/v1/accounts",
    "/api/v1/publications",
    "/media/0b6f",
)


def _render() -> str:
    """Render the OpenPost vhost with stubbed includes and lookups.

    Returns:
        The rendered vhost text.
    """
    env = Environment(
        autoescape=select_autoescape(default=False, default_for_string=False),
        undefined=StrictUndefined,
        loader=ChoiceLoader([DictLoader(STUBS), FileSystemLoader(str(PROJECT_ROOT))]),
    )
    env.filters["urlsplit"] = lambda value, part: getattr(urlsplit(value), part)
    answers = {"sso": False, "domain": DOMAIN, "network_handover": False}
    env.globals["lookup"] = lambda name, *_args, **_kwargs: answers[name]
    return env.get_template(PROXY_TEMPLATE).render(
        application_id="web-app-openpost",
        domain=DOMAIN,
        OIDC={"URL": "https://auth.example.test/realms/main"},
    )


def _echo_location(rendered: str) -> tuple[str, str, str]:
    """Return the location, forwarded proto and extra block of the Echo location.

    Args:
        rendered: the rendered vhost text.

    Returns:
        The location argument, the X-Forwarded-Proto value and the extra configuration.
    """
    found = re.findall(
        r"LOCATION\[(.*?)\]PROTO\[(.*?)\]EXTRA\[(.*?)\]END", rendered, re.DOTALL
    )
    if len(found) != 1:
        raise AssertionError(f"expected one Echo location, found {len(found)}")
    return found[0]


class TestProxyEchoOrigin(unittest.TestCase):
    def test_the_echo_location_matches_every_cookie_echo_route_and_no_huma_route(
        self,
    ) -> None:
        location, _, _ = _echo_location(_render())
        modifier, quoted = location.split(" ", 1)
        self.assertEqual(modifier, "~")
        pattern = re.compile(quoted.strip('"'))
        for route in ECHO_ROUTES:
            self.assertRegex(route, pattern)
        for route in HUMA_ROUTES:
            self.assertNotRegex(route, pattern)

    def test_the_echo_location_forwards_plain_http(self) -> None:
        _, proto, _ = _echo_location(_render())
        self.assertEqual(proto, "http")

    def test_the_echo_location_downgrades_only_its_own_https_origin(self) -> None:
        _, _, extra = _echo_location(_render())
        self.assertIn('if ($http_origin = "https://$host") {', extra)
        self.assertIn('set $openpost_origin "http://$host";', extra)
        self.assertIn("proxy_set_header Origin $openpost_origin;", extra)

    def test_the_regular_locations_stay_in_place(self) -> None:
        rendered = _render()
        self.assertIn("SSO_ACL", rendered)
        self.assertNotIn("HANDOVER", rendered)


if __name__ == "__main__":
    unittest.main()
