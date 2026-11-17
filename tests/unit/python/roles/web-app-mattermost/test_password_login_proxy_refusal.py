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

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVER

ROLE = "web-app-mattermost"
ROLE_DIR = PROJECT_ROOT / "roles" / ROLE
REFUSED = ("= /api/v4/users/login", "= /api/v4/users/login/switch")
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
        return "proxy_pass http://mattermost;"
    if kind == "config":
        return args[2]
    raise AssertionError(f"unexpected lookup({kind!r}, ...)")


def render(sso: bool) -> str:
    """
    Args:
        sso: the role's ``MATTERMOST_OIDC_ENABLED``.

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
    )
    environment.filters["bool"] = bool
    environment.filters["entity_name"] = lambda value: value.rsplit("-", 1)[-1]
    return environment.get_template(f"roles/{ROLE}/templates/{extra}").render(
        application_id=ROLE,
        MATTERMOST_OIDC_ENABLED=sso,
        http_port=8065,
        proxy_service_key="mattermost",
        lookup=_lookup,
    )


def locations(rendered: str) -> dict[str, list[str]]:
    """
    Args:
        rendered: an nginx fragment.

    Returns:
        Every location's matcher, modifier included, with its directives.
    """
    return {
        match.group(1).strip(): [
            line.strip() for line in match.group(2).splitlines() if line.strip()
        ]
        for match in re.finditer(
            r"^location\s+([^{\n]+?)\s*\{((?:[^{}]|\{[^{}]*\})*)\}",
            rendered,
            re.MULTILINE,
        )
    }


def top_level(directives: list[str]) -> list[str]:
    """
    Args:
        directives: the stripped lines of one location body.

    Returns:
        The lines outside any nested block such as ``if``.
    """
    depth, kept = 0, []
    for line in directives:
        if depth == 0:
            kept.append(line)
        depth += line.count("{") - line.count("}")
    return kept


class TestPasswordLoginIsRefusedAtTheProxy(unittest.TestCase):
    def test_sso_refuses_exactly_the_password_endpoints(self) -> None:
        found = locations(render(sso=True))
        self.assertEqual(sorted(REFUSED), sorted(found))
        for matcher, directives in found.items():
            with self.subTest(matcher=matcher):
                self.assertIn("return 403;", top_level(directives))
                for kept in ("IDENTITY_STRIPS;", "SECURITY_HEADERS;", "FORWARDED;"):
                    self.assertIn(kept, directives)
                self.assertNotIn("LUA_INJECTION;", directives)

    def test_native_mode_renders_nothing(self) -> None:
        self.assertEqual("", render(sso=False).strip())


if __name__ == "__main__":
    unittest.main()
