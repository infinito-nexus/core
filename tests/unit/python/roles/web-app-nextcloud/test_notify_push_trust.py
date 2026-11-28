"""The notify_push daemon's request must reach Nextcloud from a trusted proxy,
and nothing an MCP client can reach may become one.

``occ notify_push:setup`` fails unless Nextcloud resolves the daemon's
``X-Forwarded-For`` test value, which it only does when the daemon's source
address lies inside ``trusted_proxies`` and its host is a trusted domain. Every
address ``trusted_proxies`` covers can set ``X-Forwarded-For``, because the
inner nginx passes it to PHP unchanged, so an entry covering an address an MCP
client can hold lets that client forge its address to Nextcloud. The role vars
and the daemon's ``networks:`` fragment of ``compose.yml.j2`` are rendered
against the real merged applications and the real ``config``, ``proxy_hops``
and ``container_networks`` lookups in both deployment modes.
"""

from __future__ import annotations

import contextlib
import re
import unittest
from ipaddress import ip_address, ip_network
from urllib.parse import urlsplit

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.filter.core import FilterModule
from ansible.template import Templar
from jinja2 import Environment, StrictUndefined, select_autoescape
from jinja2.nativetypes import NativeEnvironment

from plugins.lookup.applications import LookupModule as ApplicationsLookup
from plugins.lookup.container_networks import LookupModule as ContainerNetworksLookup
from plugins.lookup.proxy_hops import LookupModule as ProxyHopsLookup
from utils.cache.base import _fingerprint_scope
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.networks.address import subnet_gateway
from utils.networks.lookup_context import build_context
from utils.networks.render import compute_external_network_roles
from utils.roles.entity.name import entity_name
from utils.roles.mapping import (
    ROLE_FILE_META_MCP,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)
from utils.tests.caches import reset_caches

ROLES_DIR = PROJECT_ROOT / "roles"
APP = "web-app-nextcloud"
MCP_CLIENTS = sorted(
    path.parent.parent.name
    for path in ROLES_DIR.glob(f"*/{ROLE_FILE_META_MCP}")
    if str((load_yaml_any(str(path)) or {}).get("direction", "")) in ("client", "both")
)
GROUP_NAMES = [
    APP,
    "svc-db-mariadb",
    "svc-db-openldap",
    "svc-prx-openresty",
    *MCP_CLIENTS,
]
ROLE_VARS = load_yaml_any(str(ROLES_DIR / APP / ROLE_FILE_VARS_MAIN))
TRUSTED_DOMAINS = next(
    item["value"]
    for item in load_yaml_any(str(ROLES_DIR / APP / "vars/system.yml"))[
        "nextcloud_system_config"
    ]
    if item["parameter"] == "trusted_domains"
)
MODE_VARS = load_yaml_any(str(PROJECT_ROOT / "group_vars/all/18_swarm.yml"))
NAME = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
PUSH_SERVICE_START = "{% set service_name = NEXTCLOUD_NOTIFY_PUSH_SERVICE %}"
PUSH_NETWORKS_AFTER = (
    "{{ lookup('container_depends_on', application_id) | indent(4) }}\n"
)
PUSH_SERVICE_END = "\n  {% endif %}"
ANSIBLE_FILTERS = FilterModule().filters()


def _variables(applications: dict, mode: str) -> dict:
    return {
        "applications": applications,
        "users": {},
        "DOMAIN_PRIMARY": "infinito.test",
        "SYSTEM_EMAIL_DOMAIN": "infinito.test",
        "DIR_COMPOSITIONS": "/opt/compose/",
        "group_names": list(GROUP_NAMES),
        "DEPLOYMENT_MODE": mode,
        "application_id": APP,
        "networks": {
            "internet": {"ip4": "198.51.100.7", "ip6": "2001:db8:1::2", "dns": ""}
        },
    }


def _bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"y", "yes", "true", "on", "1"}


def _push_networks_fragment() -> str:
    text = read_text(str(ROLES_DIR / APP / ROLE_FILE_TEMPL_COMPOSE))
    begin = text.index(PUSH_NETWORKS_AFTER, text.index(PUSH_SERVICE_START))
    begin += len(PUSH_NETWORKS_AFTER)
    return text[begin : text.index(PUSH_SERVICE_END, begin)]


class _Stack:
    """One deployment mode of Nextcloud as the notify_push daemon sees it.

    Args:
        applications: the merged applications of the real role tree.
        mode: ``compose`` or ``swarm``.
    """

    def __init__(self, applications: dict, mode: str) -> None:
        self.mode = mode
        self.variables = _variables(applications, mode)
        loader = DataLoader()
        self.hops = self._lookup(ProxyHopsLookup, [APP])
        self.container_networks = self._lookup(
            ContainerNetworksLookup, [], provider_self_alias=False
        )
        lookup = ProxyHopsLookup()
        lookup._loader = loader
        lookup._templar = Templar(loader=loader)
        context = build_context(lookup, self.variables)
        self.config = context.lookup_config

        def network_roles(role: str) -> list[str]:
            return compute_external_network_roles(
                application_id=role,
                deployment_mode=mode,
                registry=context.registry,
                lookup_config=context.lookup_config,
                lookup_database=context.lookup_database,
            )

        self.subnets = self._subnets([APP, *network_roles(APP)])
        self.client_subnets = {
            name: subnet
            for client in MCP_CLIENTS
            for name, subnet in self._subnets([client, *network_roles(client)]).items()
            if name in self.subnets
        }

    def _lookup(self, module, terms: list, **kwargs):
        lookup = module()
        lookup._loader = DataLoader()
        lookup._templar = Templar(loader=lookup._loader)
        return lookup.run(terms, variables=self.variables, **kwargs)[0]

    def _subnets(self, roles: list[str]) -> dict[str, str]:
        return {
            entity_name(role): self.config(role, "networks.local.subnet", "")
            for role in dict.fromkeys(roles)
        }

    def _context(self, env: Environment, text: str, enabled: bool) -> dict:
        env.filters.update(
            {
                name: ANSIBLE_FILTERS[name]
                for name in ("from_yaml", "combine", "to_nice_yaml")
            }
        )
        env.filters["bool"] = _bool
        env.filters["entity_name"] = entity_name
        lookups = {
            "proxy_hops": lambda _application_id: list(self.hops),
            "config": lambda application_id, path: self.config(
                application_id, path, None
            ),
            "network_siblings": lambda domain: [domain],
            "container_networks": lambda: self.container_networks,
        }
        env.globals["lookup"] = lambda name, *args, **_kwargs: lookups[name](*args)
        scope = {
            "application_id": APP,
            "DEPLOYMENT_MODE": self.mode,
            "NEXTCLOUD_DOMAIN": "next.cloud.infinito.test",
            "NEXTCLOUD_NOTIFY_PUSH_ENABLED": enabled,
        }
        native = NativeEnvironment(undefined=StrictUndefined)
        native.filters.update(env.filters)
        native.globals.update(env.globals)
        for name in ("IS_COMPOSE_MODE", "IS_SWARM_MODE"):
            scope[name] = native.from_string(MODE_VARS[name]).render(scope)
        resolved: dict = {}

        def resolve(value, own: str = ""):
            if not isinstance(value, str):
                return value
            for ref in sorted(set(NAME.findall(value)) & ROLE_VARS.keys() - {own}):
                if ref not in scope and ref not in resolved:
                    resolved[ref] = resolve(ROLE_VARS[ref], ref)
            return native.from_string(value).render({**scope, **resolved})

        resolve(text)
        return {**scope, **resolved}

    def render(self, expression: str, *, enabled: bool = True):
        """Render a role-var expression natively, as Ansible would template it.

        Args:
            expression: a value of ``vars/main.yml`` or ``vars/system.yml``.
            enabled: the value of ``NEXTCLOUD_NOTIFY_PUSH_ENABLED``.
        """
        env = NativeEnvironment(undefined=StrictUndefined)
        return env.from_string(expression).render(
            self._context(env, expression, enabled)
        )

    def push_networks(self) -> dict:
        """The daemon's ``networks:`` mapping as ``compose.yml.j2`` renders it."""
        fragment = _push_networks_fragment()
        env = Environment(
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            autoescape=select_autoescape(default_for_string=False),
        )
        rendered = env.from_string(fragment).render(self._context(env, fragment, True))
        return load_yaml_str(rendered)["networks"]

    def source(self, url: str) -> tuple[str, str, str]:
        """Network and address range the daemon's request to ``url`` leaves from.

        Docker's DNS resolves ``<name>.<network>`` on that network alone and
        a bare name on the first attached network by name (moby
        ``Endpoint.Less``: equal priority and gateway, then name), which was
        mariadb in fork run 43777013536. The daemon leaves from its pinned
        ``ipv4_address`` there, else from any address of the subnet.

        Args:
            url: the ``NEXTCLOUD_URL`` the daemon receives.

        Returns:
            The URL host, the network name and the source address range.
        """
        host = urlsplit(url).hostname
        network = host.partition(".")[2] or min(self.subnets)
        pinned = (self.push_networks().get(network) or {}).get("ipv4_address")
        return host, network, f"{pinned}/32" if pinned else self.subnets[network]


def _covered(source: str, trusted: list[str]) -> bool:
    network = ip_network(source)
    return any(
        network.version == ip_network(entry, strict=False).version
        and network.subnet_of(ip_network(entry, strict=False))
        for entry in trusted
    )


class TestNotifyPushTrust(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_caches(files_changed=False)
        scope = contextlib.ExitStack()
        cls.addClassCleanup(scope.close)
        scope.enter_context(_fingerprint_scope())
        applications = ApplicationsLookup()
        applications._templar = Templar(loader=DataLoader())
        merged = applications.run(
            [], variables=_variables({}, "compose"), roles_dir=str(ROLES_DIR)
        )[0]
        cls.stacks = {mode: _Stack(merged, mode) for mode in ("compose", "swarm")}

    @classmethod
    def tearDownClass(cls) -> None:
        reset_caches(files_changed=False)

    def _assert_daemon_accepted(self, stack: _Stack) -> None:
        url = stack.render(ROLE_VARS["NEXTCLOUD_NOTIFY_PUSH_NEXTCLOUD_URL"])
        host, network, source = stack.source(url)
        trusted = stack.render(ROLE_VARS["NEXTCLOUD_TRUSTED_PROXIES"])
        self.assertIn(network, stack.push_networks())
        self.assertTrue(
            _covered(source, trusted),
            f"{url} leaves from {network} {source}, outside trusted_proxies {trusted}",
        )
        domains = stack.render(TRUSTED_DOMAINS.replace("| to_json", "| list"))
        self.assertIn(host, domains)
        self.assertEqual(
            stack.render(ROLE_VARS["NEXTCLOUD_TRUSTED_PROXIES"], enabled=False),
            stack.hops,
        )

    def _assert_no_client_reachable_trust(self, stack: _Stack) -> None:
        self.assertIn(entity_name(APP), stack.client_subnets)
        url = stack.render(ROLE_VARS["NEXTCLOUD_NOTIFY_PUSH_NEXTCLOUD_URL"])
        _, _, source = stack.source(url)
        trusted = stack.render(ROLE_VARS["NEXTCLOUD_TRUSTED_PROXIES"])
        for entry in (entry for entry in trusted if entry not in stack.hops):
            for name, subnet in stack.client_subnets.items():
                with self.subTest(entry=entry, network=name):
                    if not ip_network(entry, strict=False).overlaps(ip_network(subnet)):
                        continue
                    self.assertEqual(
                        str(ip_network(entry, strict=False)),
                        source,
                        f"trusted_proxies entry {entry} covers addresses an MCP "
                        f"client on {name} {subnet} can hold",
                    )
                    self.assertEqual(ip_network(source).prefixlen, 32)
                    self.assertNotEqual(
                        str(ip_network(source).network_address), subnet_gateway(subnet)
                    )
                    self.assertIn(ip_address(source.split("/")[0]), ip_network(subnet))

    def test_compose_daemon_request_comes_from_a_trusted_proxy(self) -> None:
        self._assert_daemon_accepted(self.stacks["compose"])

    def test_swarm_daemon_request_rides_the_overlay_proxy_hops_already_trust(
        self,
    ) -> None:
        self._assert_daemon_accepted(self.stacks["swarm"])

    def test_compose_trusts_no_address_an_mcp_client_can_hold(self) -> None:
        self._assert_no_client_reachable_trust(self.stacks["compose"])

    def test_swarm_trusts_no_address_an_mcp_client_can_hold(self) -> None:
        self._assert_no_client_reachable_trust(self.stacks["swarm"])


if __name__ == "__main__":
    unittest.main()
