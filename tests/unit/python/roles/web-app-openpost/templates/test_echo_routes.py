from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template
from jinja2 import (
    ChoiceLoader,
    DictLoader,
    Environment,
    FileSystemLoader,
    StrictUndefined,
    select_autoescape,
)

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.networks.proxy import render_proxy_pass

ROLE_DIR = PROJECT_ROOT / "roles/web-app-openpost"
TEMPLATE = "roles/web-app-openpost/templates/nginx/echo_routes.conf.j2"
DOMAIN = "publish.example.test"
LOCAL_HTTP_PORT = 8106

STUBBED_INCLUDES = {
    "roles/web-app-keycloak/templates/sso_proxy/following_directives.conf.j2": "SSO_GATE\n",
    "roles/sys-svc-proxy/templates/headers/content_security_policy.conf.j2": "",
    "roles/sys-svc-proxy/templates/headers/access_control_allow.conf.j2": "",
    "roles/sys-svc-proxy/templates/headers/untrusted_identity_strips.conf.j2": "",
    "roles/sys-front-inj-all/templates/location.lua.j2": "",
}

ECHO_ROUTES = (
    "/api/v1/media/upload",
    "/api/v1/media/batch-upload",
    "/api/v1/media/metadata",
    "/api/v1/media/upload-session/0b6f/content",
    "/api/v1/auth/profile/avatar",
    "/api/v1/admin/backup",
    "/api/v1/admin/backup/export",
    "/api/v1/admin/backup/restore/upload",
    "/api/v1/admin/backup/restore-points/nightly",
)
OTHER_ROUTES = (
    "/",
    "/api/v1/media",
    "/api/v1/media/upload-session",
    "/api/v1/media/upload-session/0b6f/complete",
    "/api/v1/media/uploads",
    "/api/v1/accounts",
    "/api/v1/publications",
    "/api/v1/admin/backups",
    "/media/0b6f",
)


def stub_lookup(deployment_mode: str, proxy_gated: bool):
    """Return a `lookup` that answers what the location template asks for.

    Args:
        deployment_mode: the mode `proxy_pass` renders for.
        proxy_gated: what `lookup('sso', ..., 'is_proxy_gated')` answers.
    """
    tls = {"protocols.web": "https", "ports.web": 443, "enabled": True}

    def lookup(kind, *args, **kwargs):
        if kind == "sso":
            return proxy_gated
        if kind == "config":
            return args[2]
        if kind == "network_handover":
            return False
        if kind == "tls":
            return tls[args[1]]
        if kind == "proxy_pass":
            return render_proxy_pass(
                f"127.0.0.1:{kwargs['local_port']}",
                deployment_mode,
                tail=kwargs["tail"],
            )
        raise AssertionError(f"unexpected lookup({kind!r}, ...)")

    return lookup


def render(deployment_mode: str = "compose", proxy_gated: bool = False) -> str:
    """Render the location the OpenPost vhost carries for its Echo routes.

    Args:
        deployment_mode: the mode `proxy_pass` renders for.
        proxy_gated: whether the application sits behind the SSO proxy gate.
    """
    env = Environment(
        loader=ChoiceLoader(
            [DictLoader(STUBBED_INCLUDES), FileSystemLoader(str(PROJECT_ROOT))]
        ),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
        trim_blocks=True,
    )
    env.filters["bool"] = lambda value: (
        value
        if isinstance(value, bool)
        else str(value).strip().lower() in {"true", "1", "yes", "on"}
    )
    env.filters["on_off"] = lambda value: "on" if value else "off"
    env.filters["entity_name"] = lambda value: value.rsplit("-", 1)[-1]
    return env.get_template(TEMPLATE).render(
        application_id="web-app-openpost",
        domain=DOMAIN,
        http_port=LOCAL_HTTP_PORT,
        lookup=stub_lookup(deployment_mode, proxy_gated),
    )


def location_block(rendered: str) -> tuple[str, list[str]]:
    """Return the matcher and the directives, one per line, of the only location.

    Args:
        rendered: the rendered fragment.
    """
    blocks = re.findall(
        r"^location\s+([^{\n]+?)\s*\{((?:[^{}]|\{[^{}]*\})*)\}", rendered, re.MULTILINE
    )
    if len(blocks) != 1:
        raise AssertionError(f"expected one location, rendered:\n{rendered}")
    matcher, body = blocks[0]
    return matcher.strip(), [line.strip() for line in body.splitlines() if line.strip()]


def matcher_pattern(matcher: str) -> re.Pattern[str]:
    """Return the regular expression of a case-sensitive regex location matcher.

    Args:
        matcher: the location matcher, modifier included.
    """
    modifier, expression = matcher.split(" ", 1)
    if modifier != "~":
        raise AssertionError(f"'{matcher}' is not a case-sensitive regex location")
    return re.compile(expression.strip('"'))


def extra_configuration(oidc_enabled: bool) -> str:
    """Evaluate the vhost extras `tasks/00_core.yml` hands to `sys-stk-full`.

    Args:
        oidc_enabled: the resolved `OPENPOST_OIDC_ENABLED`.
    """
    task = next(
        task
        for task in load_yaml_any(ROLE_DIR / "tasks/00_core.yml")
        if "vars" in task and "webserver_extra_configuration" in task["vars"]
    )
    with tempfile.TemporaryDirectory() as search_path:
        fragments = Path(search_path, "templates", "nginx")
        fragments.mkdir(parents=True)
        (fragments / "echo_routes.conf.j2").write_text(
            "ECHO_ROUTES\n", encoding="utf-8"
        )
        templar = Templar(
            loader=DataLoader(),
            variables={
                "ansible_search_path": [search_path],
                "OPENPOST_OIDC_ENABLED": oidc_enabled,
            },
        )
        return templar.template(
            trust_as_template(task["vars"]["webserver_extra_configuration"])
        )


class TestEchoRoutesLocation(unittest.TestCase):
    def test_every_cookie_echo_route_is_covered(self):
        matcher, _ = location_block(render())
        pattern = matcher_pattern(matcher)
        for path in ECHO_ROUTES:
            with self.subTest(path=path):
                self.assertRegex(path, pattern)

    def test_no_other_route_is_covered(self):
        matcher, _ = location_block(render())
        pattern = matcher_pattern(matcher)
        for path in OTHER_ROUTES:
            with self.subTest(path=path):
                self.assertNotRegex(path, pattern)

    def test_the_upstream_is_told_plain_http(self):
        _, directives = location_block(render())
        self.assertIn("proxy_set_header X-Forwarded-Proto http;", directives)
        self.assertNotIn("proxy_set_header X-Forwarded-Proto $scheme;", directives)

    def test_only_the_vhost_own_https_origin_is_downgraded(self):
        _, directives = location_block(render())
        rewrite = [
            "set $openpost_origin $http_origin;",
            'if ($http_origin = "https://$host") {',
            'set $openpost_origin "http://$host";',
            "}",
            "proxy_set_header Origin $openpost_origin;",
        ]
        start = directives.index(rewrite[0])
        self.assertEqual(directives[start : start + len(rewrite)], rewrite)

    def test_both_modes_proxy_without_a_static_uri(self):
        for mode in ("compose", "swarm"):
            with self.subTest(mode=mode):
                _, directives = location_block(render(mode))
                proxy_pass = [d for d in directives if d.startswith("proxy_pass ")]
                self.assertEqual(len(proxy_pass), 1)
                self.assertRegex(
                    proxy_pass[0], r"^proxy_pass http://[^/;]+(\$request_uri)?;$"
                )

    def test_the_location_follows_the_application_sso_gate(self):
        self.assertNotIn("SSO_GATE", render(proxy_gated=False))
        self.assertIn("SSO_GATE", render(proxy_gated=True))


class TestVhostExtras(unittest.TestCase):
    def test_the_echo_routes_location_reaches_the_vhost(self):
        self.assertEqual(extra_configuration(False), "ECHO_ROUTES\n")


if __name__ == "__main__":
    unittest.main()
