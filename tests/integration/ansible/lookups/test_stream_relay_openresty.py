"""Integration test: openresty relays public LDAPS over the openldap relay network.

Against the real role tree. Until the relay has its live swarm proof, a swarm
render of openresty or openldap with ``services.openldap.network.public`` on
fails, and so does every ``proxy_hops`` lookup that reads openresty's
networks. Past the proof (the refusal lifted), the swarm openresty and openldap
share ``openldap-relay``, openresty publishes the LDAPS port in host mode, and
no LDAP client's networks or trusted proxy addresses change. Compose, and swarm
with the switch off, keep what they rendered before.
"""

from __future__ import annotations

import contextlib
import copy
import json
import re
import unittest
import unittest.mock as mock

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.template import Templar
from jinja2 import BaseLoader, Environment, StrictUndefined, select_autoescape

from plugins.lookup.applications import (
    LookupModule as ApplicationsLookup,
)
from utils.cache.base import _fingerprint_scope
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.networks import attachments
from utils.networks.proxy import REVERSE_PROXY_APPLICATION_ID
from utils.roles.mapping import ROLE_FILE_META_NETWORKS, ROLE_FILE_TEMPL_COMPOSE
from utils.templating.ansible import _trust_as_template
from utils.tests.caches import reset_caches

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"
PROXY = REVERSE_PROXY_APPLICATION_ID
DIRECTORY = "svc-db-openldap"
CONSUMER = "web-app-nextcloud"
WEB_LDAP_CLIENTS = (CONSUMER, "web-app-lam")
LDAP_CLIENTS = (*WEB_LDAP_CLIENTS, "svc-ai-agent-provisioner")
GROUP_NAMES = [PROXY, DIRECTORY, *LDAP_CLIENTS, "svc-db-mariadb"]
COMPOSE_TEMPLATE = f"roles/{PROXY}/{ROLE_FILE_TEMPL_COMPOSE}"
PUBLIC = {DIRECTORY: {"services": {"openldap": {"network": {"public": True}}}}}
TITLE = "OpenLDAP LDAPS through openresty in swarm"
RELAY = "openldap-relay"
RELAY_NETWORK = {"name": RELAY, "subnet": "192.168.105.48/28", "stack": "openldap"}
LDAPS_HOST_PORT = (
    "      - target: 636\n"
    "        published: 636\n"
    "        protocol: tcp\n"
    "        mode: host\n"
)
REAL_LOOKUPS = ("container_ports", "container_networks", "compose_networks")
SWARM_OFF_PORTS = (
    "ports:\n"
    "      - target: 80\n"
    "        published: 80\n"
    "        protocol: tcp\n"
    "        mode: host\n"
    "      - target: 443\n"
    "        published: 443\n"
    "        protocol: tcp\n"
    "        mode: host"
)
SWARM_OFF_RENDER = (
    "  openresty:\n"
    "    \n"
    "      args:\n"
    '        OPENRESTY_IMAGE:              "openresty/openresty"\n'
    '        OPENRESTY_VERSION:            "pinned"\n'
    '        PROMETHEUS_ENABLED:           "false"\n'
    '        LUA_PROMETHEUS_URL_MAIN:      "main"\n'
    '        LUA_PROMETHEUS_URL_COUNTER:   "counter"\n'
    '        LUA_PROMETHEUS_URL_KEYS:      "keys"\n'
    "    \n"
    "    \n"
    "    ports:\n"
    "      - target: 80\n"
    "        published: 80\n"
    "        protocol: tcp\n"
    "        mode: host\n"
    "      - target: 443\n"
    "        published: 443\n"
    "        protocol: tcp\n"
    "        mode: host\n"
    "    \n"
    "    \n"
    "    networks:\n"
    "      openresty:\n"
    "        aliases:\n"
    "          - openresty\n"
    "          - forum.infinito.test\n"
    "          - auth.infinito.test\n"
    "          - next.cloud.infinito.test\n"
    "          - blog.infinito.test\n"
    "          - api.seaweedfs.s3.infinito.test\n"
    "      default:\n"
    "    \n"
    "    ulimits:\n"
    "      nofile:\n"
    "        soft: 4096\n"
    "        hard: 4096\n"
    '    command: ["openresty", "-g", "daemon off;"]\n'
    "    \n"
    "\n"
    "\n"
    "networks:\n"
    "  openresty:\n"
    "    external: true\n"
    "  default:\n"
    "    driver: overlay\n"
    "    attachable: true\n"
    "    driver_opts:\n"
    '      encrypted: "true"\n'
    "\n"
)


def _subnet(role: str) -> str:
    return load_yaml(str(ROLES_DIR / role / ROLE_FILE_META_NETWORKS))["local"]["subnet"]


def _variables(applications: dict, mode: str, application_id: str) -> dict:
    return {
        "applications": applications,
        "users": {},
        "DOMAIN_PRIMARY": "infinito.test",
        "SYSTEM_EMAIL_DOMAIN": "infinito.test",
        "DIR_COMPOSITIONS": "/opt/compose/",
        "group_names": list(GROUP_NAMES),
        "DEPLOYMENT_MODE": mode,
        "application_id": application_id,
        "networks": {"internet": {"ip4": "198.51.100.7", "ip6": "", "dns": ""}},
    }


_MERGED: dict[str, dict] = {}


def _merged(overrides: dict) -> dict:
    key = json.dumps(overrides, sort_keys=True)
    if key not in _MERGED:
        reset_caches(files_changed=False)
        applications = ApplicationsLookup()
        applications._templar = Templar(loader=DataLoader())
        _MERGED[key] = applications.run(
            [],
            variables=_variables(overrides, "compose", PROXY),
            roles_dir=str(ROLES_DIR),
        )[0]
    return copy.deepcopy(_MERGED[key])


def _open_fingerprint_scope(cls: type) -> None:
    scope = contextlib.ExitStack()
    cls.addClassCleanup(scope.close)
    scope.enter_context(_fingerprint_scope())


def _run(name: str, terms: list, variables: dict, **kwargs) -> list:
    loader = DataLoader()
    plugin = lookup_loader.get(name, loader=loader, templar=Templar(loader=loader))
    return plugin.run(terms, variables=variables, **kwargs)


class _MainOnly(BaseLoader):
    def get_source(self, environment, template):
        if template == COMPOSE_TEMPLATE:
            return read_text(str(PROJECT_ROOT / template)), template, lambda: True
        return "", template, lambda: True


def _compose(applications: dict, mode: str) -> str:
    variables = _variables(applications, mode, PROXY)
    env = Environment(
        loader=_MainOnly(),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )

    def lookup(name: str, *terms, **kwargs):
        if name in REAL_LOOKUPS:
            return _run(name, list(terms), variables, **kwargs)[0]
        return ""

    def query(name: str, *terms, **kwargs):
        return _run(name, list(terms), variables, **kwargs)

    return env.get_template(COMPOSE_TEMPLATE).render(
        lookup=lookup,
        query=query,
        IS_SWARM_MODE=mode == "swarm",
        OPENRESTY_IMAGE="openresty/openresty",
        OPENRESTY_VERSION="pinned",
        OPENRESTY_PROMETHEUS_ENABLED="false",
        OPENRESTY_LUA_PROMETHEUS_URL_MAIN="main",
        OPENRESTY_LUA_PROMETHEUS_URL_COUNTER="counter",
        OPENRESTY_LUA_PROMETHEUS_URL_KEYS="keys",
        OPENRESTY_CONTAINER="openresty",
        WEBSERVER_PROXY_WORKER_RLIMIT_NOFILE=4096,
        **variables,
    )


def _ports_through_templar(applications: dict, mode: str) -> str:
    """Render the ``ports`` expression of the real template with Ansible's Templar.

    Args:
      applications: the merged applications.
      mode: the DEPLOYMENT_MODE.

    Returns:
      the ports block that Ansible's own ``lookup`` and ``query`` produce.
    """
    source = read_text(str(PROJECT_ROOT / COMPOSE_TEMPLATE))
    start = source.index("{{ lookup('container_ports',")
    end = source.index("}}", source.index("*query('stream_relay_ports')")) + 2
    templar = Templar(
        loader=DataLoader(), variables=_variables(applications, mode, PROXY)
    )
    return templar.template(_trust_as_template(source[start:end]))


def _messages(error: BaseException) -> str:
    seen: list[str] = []
    current: BaseException | None = error
    while current is not None:
        seen.append(str(current))
        current = current.__cause__ or current.__context__
    return "\n".join(seen)


def _proven():
    return mock.patch.object(attachments, "UNPROVEN_STREAM_RELAY_MODES", frozenset())


class _BothSwitchStates:
    @classmethod
    def setUpClass(cls) -> None:
        _open_fingerprint_scope(cls)
        cls.off = _merged({})
        cls.on = _merged(PUBLIC)
        cls.proof = _proven()
        cls.proof.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.proof.stop()
        reset_caches(files_changed=False)

    def _both(self, name: str, terms: list, mode: str, application_id: str) -> tuple:
        return tuple(
            _run(name, terms, _variables(apps, mode, application_id))
            for apps in (self.off, self.on)
        )


class TestTheRelayIsRefusedInSwarmUntilItsProof(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _open_fingerprint_scope(cls)
        cls.off = _merged({})
        cls.on = _merged(PUBLIC)

    @classmethod
    def tearDownClass(cls) -> None:
        reset_caches(files_changed=False)

    def _assert_refused(self, call) -> None:
        with self.assertRaises(Exception) as raised:
            call()
        self.assertIn(TITLE, _messages(raised.exception))

    def test_a_swarm_render_of_openresty_with_the_switch_on_fails(self):
        self._assert_refused(lambda: _compose(self.on, "swarm"))

    def test_ansibles_own_query_of_the_relay_ports_fails(self):
        self._assert_refused(lambda: _ports_through_templar(self.on, "swarm"))

    def test_openldap_and_every_proxied_client_fail_too(self):
        lookups = (
            ("container_networks", [], DIRECTORY),
            ("stream_relay_networks", [], PROXY),
            ("proxy_hops", [CONSUMER], CONSUMER),
        )
        for name, terms, application_id in lookups:
            with self.subTest(lookup=name, application_id=application_id):
                self._assert_refused(
                    lambda name=name, terms=terms, app=application_id: _run(
                        name, terms, _variables(self.on, "swarm", app)
                    )
                )

    def test_the_switch_off_and_compose_render(self):
        self.assertEqual(_compose(self.off, "swarm"), SWARM_OFF_RENDER)
        self.assertEqual(_compose(self.on, "compose"), _compose(self.off, "compose"))


class TestOpenrestyRelaysLdapsInSwarm(_BothSwitchStates, unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.renders = {
            (public, mode): _compose(cls.on if public else cls.off, mode)
            for public in (False, True)
            for mode in ("compose", "swarm")
        }

    def test_swarm_with_the_switch_on_publishes_ldaps_in_host_mode(self):
        self.assertIn(LDAPS_HOST_PORT, self.renders[(True, "swarm")])

    def test_ansibles_own_query_publishes_ldaps_only_with_the_switch_on(self):
        off = _ports_through_templar(self.off, "swarm")
        self.assertEqual(off, SWARM_OFF_PORTS)
        self.assertEqual(
            _ports_through_templar(self.on, "swarm"),
            f"{off}\n{LDAPS_HOST_PORT.rstrip()}",
        )

    def test_swarm_with_the_switch_on_joins_the_relay_network_only(self):
        rendered = self.renders[(True, "swarm")]
        self.assertIn(RELAY, _service_networks(rendered))
        self.assertNotIn("openldap", _service_networks(rendered))
        self.assertIn(f"  {RELAY}:\n    external: true", _networks_block(rendered))
        self.assertNotIn("  openldap:\n", _networks_block(rendered))

    def test_swarm_with_the_switch_on_pre_creates_the_relay_network(self):
        for application_id in (PROXY, DIRECTORY):
            with self.subTest(application_id=application_id):
                off, on = self._both(
                    "stream_relay_networks", [], "swarm", application_id
                )
                self.assertEqual((off, on), ([[]], [[RELAY_NETWORK]]))

    def test_the_switch_leaves_the_pre_created_role_overlays_unchanged(self):
        for application_id in (PROXY, DIRECTORY, *LDAP_CLIENTS):
            with self.subTest(application_id=application_id):
                off, on = self._both(
                    "compose_external_networks", [], "swarm", application_id
                )
                self.assertEqual(on, off)

    def test_swarm_with_the_switch_off_renders_as_before(self):
        self.assertEqual(self.renders[(False, "swarm")], SWARM_OFF_RENDER)

    def test_the_switch_on_adds_only_the_port_and_the_relay_network(self):
        on = self.renders[(True, "swarm")]
        for added in (
            LDAPS_HOST_PORT,
            f"      {RELAY}:\n        {{}}\n",
            f"  {RELAY}:\n    external: true\n",
        ):
            self.assertIn(added, on)
            on = on.replace(added, "", 1)
        self.assertEqual(on, SWARM_OFF_RENDER)

    def test_compose_with_the_switch_on_renders_as_with_it_off(self):
        self.assertEqual(
            self.renders[(True, "compose")], self.renders[(False, "compose")]
        )

    def test_compose_keeps_the_host_network_and_publishes_nothing(self):
        rendered = self.renders[(True, "compose")]
        self.assertIn('network_mode: "host"', rendered)
        self.assertNotIn("ports:", rendered)
        self.assertNotIn("openldap", rendered)

    def test_the_relay_term_reads_the_ldaps_port_of_openldap(self):
        self.assertEqual(
            _run("stream_relay_ports", [], _variables(self.on, "swarm", PROXY)),
            [
                {
                    "service": "openldap",
                    "protocol": "ldaps",
                    "application_id": DIRECTORY,
                    "container": "same",
                    "mode": "host",
                }
            ],
        )


class TestOpenldapJoinsTheRelayNetwork(_BothSwitchStates, unittest.TestCase):
    def test_swarm_with_the_switch_on_adds_the_relay_network_under_the_alias(self):
        off, on = self._both("container_networks", [], "swarm", DIRECTORY)
        block = f"\n  {RELAY}:\n    aliases:\n      - openldap"
        self.assertIn(block, on[0])
        self.assertEqual(on[0].replace(block, "", 1), off[0])

    def test_compose_renders_the_same_with_the_switch_on(self):
        for name in ("container_networks", "compose_networks"):
            with self.subTest(name=name):
                off, on = self._both(name, [], "compose", DIRECTORY)
                self.assertEqual(on, off)


class TestLdapClientsKeepTheirNetworksAndProxyTrust(
    _BothSwitchStates, unittest.TestCase
):
    def test_the_clients_are_ldap_consumers_in_swarm(self):
        for client in LDAP_CLIENTS:
            with self.subTest(client=client):
                _, on = self._both("compose_external_networks", [], "swarm", client)
                self.assertIn(DIRECTORY, on[0])

    def test_a_client_attaches_the_same_with_the_switch_on(self):
        for client in LDAP_CLIENTS:
            for mode in ("compose", "swarm"):
                with self.subTest(client=client, mode=mode):
                    off, on = self._both("container_networks", [], mode, client)
                    self.assertEqual(on, off)
                    self.assertNotIn(RELAY, on[0])

    def test_the_proxy_hops_of_a_client_are_equal_with_the_relay_off_and_on(self):
        for client in WEB_LDAP_CLIENTS:
            for mode in ("compose", "swarm"):
                with self.subTest(client=client, mode=mode):
                    off, on = self._both("proxy_hops", [client], mode, client)
                    self.assertEqual(on, off)

    def test_swarm_never_trusts_the_openldap_overlay_as_a_proxy(self):
        for client in WEB_LDAP_CLIENTS:
            with self.subTest(client=client):
                _, on = self._both("proxy_hops", [client], "swarm", client)
                self.assertNotIn(_subnet(DIRECTORY), on[0])


def _networks_block(rendered: str) -> str:
    return rendered[rendered.rindex("\nnetworks:") :]


def _service_networks(rendered: str) -> list[str]:
    block = re.search(r"\n    networks:\n((?:      .*\n)+)", rendered)
    return re.findall(r"^      (\S+):", block.group(1), re.MULTILINE) if block else []


if __name__ == "__main__":
    unittest.main()
