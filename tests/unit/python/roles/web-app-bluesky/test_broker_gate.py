"""The login broker trusts X-Forwarded-Preferred-Username without an SSO check of
its own, and it publishes ``ports.local.http`` on ``DOCKER_BIND_HOST``. Without
SSO no oauth2-proxy sets that header and the vhost serves the social-app
directly, so a rendered broker would only be a header-trust port nobody gates.

The real ``compose.yml.j2`` is rendered with its lookups stubbed.
"""

from __future__ import annotations

import json
import unittest

from jinja2 import DictLoader, Environment

from utils.cache import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE, ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles/web-app-bluesky"
TEMPLATE = "compose.yml.j2"
INCLUDES = {
    "roles/sys-svc-compose/templates/base.yml.j2": "services:\n",
    "roles/sys-svc-container/templates/base.yml.j2": "",
    "roles/sys-svc-container/templates/deploy.yml.j2": "",
}


class _Stub(str):
    __slots__ = ()

    def __getattr__(self, _name: str) -> _Stub:
        return _Stub("")


def _lookup(*_args, **_kwargs) -> _Stub:
    return _Stub("")


def _services(*, web: bool, broker: bool) -> list[str]:
    env = Environment(
        autoescape=False,  # noqa: S701 - renders compose YAML, not markup
        loader=DictLoader(
            {TEMPLATE: read_text(str(ROLE / ROLE_FILE_TEMPL_COMPOSE)), **INCLUDES}
        ),
    )
    env.filters["bool"] = bool
    env.filters["to_json"] = json.dumps
    env.globals["lookup"] = _lookup
    rendered = env.get_template(TEMPLATE).render(
        BLUESKY_WEB_ENABLED=web,
        BLUESKY_BROKER_ENABLED=broker,
        BLUESKY_BROKER_SERVICE="broker",
        BLUESKY_ADMIN_PASSWORD="x",
        OIDC={"ATTRIBUTES": {"NAME": "name"}},
    )
    return sorted(load_yaml_str(rendered)["services"])


class TestBrokerRendersOnlyWithSso(unittest.TestCase):
    def test_without_sso_the_broker_is_not_rendered(self) -> None:
        self.assertEqual(["pds", "web"], _services(web=True, broker=False))

    def test_with_sso_the_broker_is_rendered(self) -> None:
        self.assertEqual(["broker", "pds", "web"], _services(web=True, broker=True))

    def test_without_the_web_client_neither_is_rendered(self) -> None:
        self.assertEqual(["pds"], _services(web=False, broker=False))

    def test_the_broker_switch_needs_the_web_client_and_sso(self) -> None:
        switch = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))[
            "BLUESKY_BROKER_ENABLED"
        ]
        self.assertIn("BLUESKY_WEB_ENABLED", switch)
        self.assertIn("services.sso.enabled", switch)
        self.assertIn(" and ", switch)


if __name__ == "__main__":
    unittest.main()
