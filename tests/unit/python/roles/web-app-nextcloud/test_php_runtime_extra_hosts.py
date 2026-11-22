from __future__ import annotations

import itertools
import unittest
from unittest.mock import patch

from jinja2 import ChainableUndefined, DictLoader, Environment, select_autoescape

from plugins.lookup.container_extra_hosts import LookupModule as ExtraHostsLookup
from utils.cache.files import PROJECT_ROOT, read_text
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE

APPLICATION_ID = "web-app-nextcloud"
TEMPLATE = read_text(
    str(PROJECT_ROOT / "roles" / APPLICATION_ID / ROLE_FILE_TEMPL_COMPOSE)
)
ONION_PROVIDER = "auth." + "b" * 56 + ".onion"
CLEARNET_PROVIDER = "auth.infinito.example"
ONION_PINS = ["host.docker.internal:host-gateway", f"{ONION_PROVIDER}:host-gateway"]
PHP_RUNTIMES = ("nextcloud", "cron", "taskprocessing")
HEALTHCHECK_TAIL = "      start_interval: 5s\n"
DEPENDS_ON = "    {{ lookup('container_depends_on'"
PIN = "    {{ lookup('container_extra_hosts') | indent(4) }}\n"


class _Marker(ChainableUndefined):
    def __str__(self):
        return f"<{self._undefined_name}>"

    __repr__ = __str__


def _bool(value):
    if isinstance(value, bool):
        return value
    if value is None or isinstance(value, ChainableUndefined):
        return False
    return str(value).strip().lower() in {"y", "yes", "true", "on", "1"}


class _ProviderLookup:
    def __init__(self, name: str, provider_host: str):
        self._name = name
        self._provider_host = provider_host

    def run(self, terms, variables=None):
        if self._name == "config":
            return [terms[1] == "services.sso.enabled"]
        if self._name == "tls":
            return [self._provider_host]
        raise AssertionError(f"unexpected lookup '{self._name}'")


def _render(template_text: str, provider_host: str) -> str:
    """
    Args:
        template_text: the compose template source to render.
        provider_host: the SSO provider domain the extra_hosts lookup resolves.

    Returns:
        The compose document of a compose-mode node with SSO enabled, rendered
        with the real container_extra_hosts lookup.
    """
    env = Environment(
        loader=DictLoader(
            {
                "roles/sys-svc-compose/templates/base.yml.j2": "services:\n",
                "roles/sys-svc-container/templates/base.yml.j2": "    <container-base>\n",
                "roles/sys-svc-container/templates/deploy.yml.j2": "    <container-deploy>\n",
                "compose.yml.j2": template_text,
            }
        ),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        undefined=_Marker,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["bool"] = _bool
    variables = {
        "application_id": APPLICATION_ID,
        "DEPLOYMENT_MODE": "compose",
        "IS_COMPOSE_MODE": True,
        "IS_SWARM_MODE": False,
        "NEXTCLOUD_PROXY_SERVICE": "proxy",
        "NEXTCLOUD_SERVICE": "nextcloud",
        "NEXTCLOUD_CRON_SERVICE": "cron",
        "NEXTCLOUD_TASKPROCESSING_SERVICE": "taskprocessing",
    }

    def lookup(name, *args, **kwargs):
        if name == "container_extra_hosts":
            return ExtraHostsLookup().run(None, variables=variables, **kwargs)[0]
        return f"<lookup {name} {args!r}>"

    env.globals["lookup"] = lookup
    with patch(
        "plugins.lookup.container_extra_hosts.lookup_loader.get",
        side_effect=lambda name, **_kwargs: _ProviderLookup(name, provider_host),
    ):
        return env.get_template("compose.yml.j2").render(variables)


def _extra_hosts(rendered: str, service: str) -> list[str]:
    """
    Args:
        rendered: a rendered compose document.
        service: the service whose extra_hosts entries to read.

    Returns:
        The service's extra_hosts entries in order, empty when it has none.
    """
    lines = rendered.splitlines()
    body = list(
        itertools.takewhile(
            lambda line: not line.strip() or line.startswith("   "),
            lines[lines.index(f"  {service}:") + 1 :],
        )
    )
    if "    extra_hosts:" not in body:
        return []
    entries = itertools.takewhile(
        lambda line: line.startswith("      - "),
        body[body.index("    extra_hosts:") + 1 :],
    )
    return [line.removeprefix("      - ").strip('"') for line in entries]


class TestPhpRuntimeExtraHosts(unittest.TestCase):
    def test_onion_sso_pins_the_tor_proxy_host_in_every_php_runtime(self):
        rendered = _render(TEMPLATE, ONION_PROVIDER)
        for service in PHP_RUNTIMES:
            with self.subTest(service=service):
                self.assertEqual(_extra_hosts(rendered, service), ONION_PINS)

    def test_clearnet_sso_pins_nothing_in_any_php_runtime(self):
        rendered = _render(TEMPLATE, CLEARNET_PROVIDER)
        for service in PHP_RUNTIMES:
            with self.subTest(service=service):
                self.assertEqual(_extra_hosts(rendered, service), [])

    def test_negative_control_the_unpinned_template_leaves_cron_without_the_proxy_host(
        self,
    ):
        pre_fix = TEMPLATE.replace(
            HEALTHCHECK_TAIL + PIN + DEPENDS_ON, HEALTHCHECK_TAIL + DEPENDS_ON
        )
        self.assertNotEqual(pre_fix, TEMPLATE)
        rendered = _render(pre_fix, ONION_PROVIDER)
        self.assertEqual(_extra_hosts(rendered, "nextcloud"), ONION_PINS)
        self.assertEqual(_extra_hosts(rendered, "cron"), [])
        self.assertEqual(_extra_hosts(rendered, "taskprocessing"), [])


if __name__ == "__main__":
    unittest.main()
