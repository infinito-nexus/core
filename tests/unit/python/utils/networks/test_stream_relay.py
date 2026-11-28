from __future__ import annotations

import copy
import unittest
import unittest.mock as mock
from typing import ClassVar

from utils.networks import attachments
from utils.networks.attachments import _compute_attachments, stream_relay_active
from utils.networks.render import (
    compute_external_network_roles,
    render_compose_networks,
    render_container_networks,
)
from utils.networks.stream_relay import stream_relay_networks, stream_relay_ports

from ._render_helpers import _const_lookup_database, _entity_name, _role_lookup_config

PROXY = "svc-prx-openresty"
PROVIDER = "svc-db-openldap"
SWITCH = "services.openldap.network.public"
SUBNET = "192.168.105.48/28"
TITLE = "OpenLDAP LDAPS through openresty in swarm"
LDAP_FLAGS = {"services.ldap.enabled": True, "services.ldap.shared": True}
RELAY_NETWORK = {"name": "openldap-relay", "subnet": SUBNET, "stack": "openldap"}

ENTRY: dict = {
    "role": PROVIDER,
    "entity_name": "openldap",
    "provides": "ldap",
    "overlay": {
        "modes": ["compose", "swarm"],
        "topology": "shared_net",
        "stream_relay": {"switch": SWITCH, "ports": ["ldaps"], "subnet": SUBNET},
    },
}

REGISTRY: dict = {
    "ldap": ENTRY,
    "openresty": {
        "role": PROXY,
        "entity_name": "openresty",
        "overlay": {
            "modes": ["swarm"],
            "topology": "shared_net",
            "collect_proxy_resolvable": True,
            "consumer": {"kind": "web_facing"},
        },
    },
}

PROXY_RELAY = {
    "role": PROVIDER,
    "network": "openldap-relay",
    "topology": "stream_relay",
    "aliases": [],
    "is_provider": False,
}
PROVIDER_RELAY = {**PROXY_RELAY, "aliases": ["openldap"], "is_provider": True}

LDAPS = {
    "service": "openldap",
    "protocol": "ldaps",
    "application_id": PROVIDER,
    "container": "same",
    "mode": "host",
}


def _config(*, public, proxy_modes=("swarm",), ldap_consumer=None):
    per_role = {
        PROXY: {"networks.overlay.modes": list(proxy_modes)},
        PROVIDER: {SWITCH: public},
    }
    if ldap_consumer:
        per_role[ldap_consumer] = dict(LDAP_FLAGS)
    return _role_lookup_config(per_role)


def _attachments(application_id, mode, public, ldap_consumer=None):
    attachments, _ = _compute_attachments(
        REGISTRY,
        application_id,
        mode,
        _config(public=public, ldap_consumer=ldap_consumer),
        _const_lookup_database(),
    )
    return attachments


def _relays(application_id, mode, public, ldap_consumer=None):
    return [
        att
        for att in _attachments(application_id, mode, public, ldap_consumer)
        if att["topology"] == "stream_relay"
    ]


def _relay_kwargs(application_id, mode, public, registry):
    return {
        "application_id": application_id,
        "deployment_mode": mode,
        "registry": registry or REGISTRY,
        "lookup_config": _config(public=public),
    }


def _ports(*, application_id=PROXY, mode="swarm", public=True, registry=None):
    return stream_relay_ports(**_relay_kwargs(application_id, mode, public, registry))


def _networks(*, application_id=PROXY, mode="swarm", public=True, registry=None):
    return stream_relay_networks(
        **_relay_kwargs(application_id, mode, public, registry)
    )


def _proven():
    return mock.patch.object(attachments, "UNPROVEN_STREAM_RELAY_MODES", frozenset())


def _external_roles(application_id, public, ldap_consumer=None):
    return compute_external_network_roles(
        application_id=application_id,
        deployment_mode="swarm",
        registry=REGISTRY,
        lookup_config=_config(public=public, ldap_consumer=ldap_consumer),
        lookup_database=_const_lookup_database(),
    )


class TestTheRelayIsRefusedUntilItsSwarmProof(unittest.TestCase):
    def test_swarm_with_the_switch_on_is_refused_with_the_requirement(self):
        with self.assertRaisesRegex(ValueError, TITLE) as raised:
            stream_relay_active(ENTRY, "swarm", _config(public=True))
        self.assertIn(SWITCH, str(raised.exception))

    def test_every_relay_lookup_of_the_proxy_and_the_provider_is_refused(self):
        for app in (PROXY, PROVIDER):
            with self.subTest(app=app):
                with self.assertRaisesRegex(ValueError, TITLE):
                    _attachments(app, "swarm", True)
                with self.assertRaisesRegex(ValueError, TITLE):
                    _networks(application_id=app)
                with self.assertRaisesRegex(ValueError, TITLE):
                    _external_roles(app, True)
        with self.assertRaisesRegex(ValueError, TITLE):
            _ports()

    def test_the_switch_off_and_compose_pass(self):
        self.assertFalse(stream_relay_active(ENTRY, "swarm", _config(public=False)))
        self.assertFalse(stream_relay_active(ENTRY, "compose", _config(public=True)))

    def test_a_role_beside_the_relay_is_not_refused(self):
        self.assertEqual(_relays("web-app-nextcloud", "swarm", True), [])


@_proven()
class TestTheRelayIsActiveOnlyWhereTheProxyRunsOnOverlays(unittest.TestCase):
    def test_swarm_with_the_switch_on_is_active(self):
        self.assertTrue(stream_relay_active(ENTRY, "swarm", _config(public=True)))

    def test_compose_is_inactive_because_the_proxy_runs_on_the_host_network(self):
        self.assertFalse(stream_relay_active(ENTRY, "compose", _config(public=True)))

    def test_the_switch_off_is_inactive(self):
        self.assertFalse(stream_relay_active(ENTRY, "swarm", _config(public=False)))

    def test_a_string_switch_is_read_as_a_flag(self):
        self.assertTrue(stream_relay_active(ENTRY, "swarm", _config(public="True")))

    def test_the_modes_come_from_the_proxys_own_overlay(self):
        config = _config(public=True, proxy_modes=("compose", "swarm"))
        self.assertTrue(stream_relay_active(ENTRY, "compose", config))

    def test_the_switch_is_read_from_the_provider_not_the_proxy(self):
        config = _role_lookup_config(
            {PROXY: {"networks.overlay.modes": ["swarm"], SWITCH: True}}
        )
        self.assertFalse(stream_relay_active(ENTRY, "swarm", config))

    def test_a_provider_without_stream_relay_has_none(self):
        entry = copy.deepcopy(ENTRY)
        del entry["overlay"]["stream_relay"]
        self.assertFalse(stream_relay_active(entry, "swarm", _config(public=True)))

    def test_a_relay_without_a_switch_fails_loudly(self):
        entry = copy.deepcopy(ENTRY)
        del entry["overlay"]["stream_relay"]["switch"]
        with self.assertRaisesRegex(ValueError, "stream_relay needs a switch"):
            stream_relay_active(entry, "swarm", _config(public=True))


@_proven()
class TestOnlyTheProxyAndTheProviderJoinTheRelayNetwork(unittest.TestCase):
    def test_the_proxy_joins_the_relay_network_without_aliases(self):
        self.assertEqual(_relays(PROXY, "swarm", True), [PROXY_RELAY])

    def test_the_provider_joins_the_relay_network_under_its_entity_alias(self):
        self.assertEqual(_relays(PROVIDER, "swarm", True), [PROVIDER_RELAY])

    def test_the_proxy_does_not_join_the_provider_overlay(self):
        joined = [
            att["role"]
            for att in _attachments(PROXY, "swarm", True)
            if att["topology"] != "stream_relay"
        ]
        self.assertNotIn(PROVIDER, joined)

    def test_an_ldap_consumer_stays_off_the_relay_network(self):
        app = "web-app-nextcloud"
        self.assertEqual(_relays(app, "swarm", True, ldap_consumer=app), [])
        self.assertIn(
            {
                "role": PROVIDER,
                "topology": "shared_net",
                "aliases": [],
                "is_provider": False,
            },
            _attachments(app, "swarm", True, ldap_consumer=app),
        )

    def test_another_role_stays_off_the_relay_network(self):
        for app in ("svc-ai-agent-provisioner", "web-svc-xmpp", "web-app-nextcloud"):
            with self.subTest(app=app):
                self.assertEqual(_relays(app, "swarm", True), [])

    def test_nothing_joins_with_the_switch_off(self):
        for app in (PROXY, PROVIDER):
            with self.subTest(app=app):
                self.assertEqual(_relays(app, "swarm", False), [])

    def test_nothing_joins_in_compose(self):
        for app in (PROXY, PROVIDER):
            with self.subTest(app=app):
                self.assertEqual(_relays(app, "compose", True), [])


@_proven()
class TestTheRelayNetworkRenders(unittest.TestCase):
    KWARGS: ClassVar[dict] = {
        "deployment_mode": "swarm",
        "registry": REGISTRY,
        "entity_name": _entity_name,
        "lookup_database": _const_lookup_database(),
    }

    def _container(self, application_id, public):
        return render_container_networks(
            application_id=application_id,
            lookup_config=_config(public=public),
            **self.KWARGS,
        )

    def _compose(self, application_id, public):
        return render_compose_networks(
            application_id=application_id,
            lookup_config=_config(public=public),
            **self.KWARGS,
        )

    def test_the_proxy_attaches_the_relay_network_and_not_the_overlay(self):
        rendered = self._container(PROXY, True)
        self.assertIn("\n  openldap-relay:\n    {}", rendered)
        self.assertNotIn("\n  openldap:", rendered)

    def test_the_provider_attaches_the_relay_network_with_its_alias(self):
        self.assertIn(
            "\n  openldap-relay:\n    aliases:\n      - openldap",
            self._container(PROVIDER, True),
        )

    def test_both_compose_files_reference_the_relay_network_as_external(self):  # nocheck: test.text-presence -- asserts on the compose networks the renderer emits, which it runs  # fmt: skip
        for app in (PROXY, PROVIDER):
            with self.subTest(app=app):
                self.assertIn(
                    "  openldap-relay:\n    external: true\n", self._compose(app, True)
                )

    def test_the_switch_off_renders_no_relay_network(self):
        for app in (PROXY, PROVIDER):
            with self.subTest(app=app):
                self.assertNotIn("relay", self._container(app, False))
                self.assertNotIn("relay", self._compose(app, False))

    def test_the_switch_adds_exactly_the_relay_block(self):
        blocks = {
            PROXY: "\n  openldap-relay:\n    {}",
            PROVIDER: "\n  openldap-relay:\n    aliases:\n      - openldap",
        }
        for app, block in blocks.items():
            with self.subTest(app=app):
                on = self._container(app, True)
                self.assertIn(block, on)
                self.assertEqual(on.replace(block, "", 1), self._container(app, False))


@_proven()
class TestTheRelayIsNoRoleNetwork(unittest.TestCase):
    def test_the_switch_leaves_the_external_roles_of_every_side_unchanged(self):
        consumer = "web-app-nextcloud"
        for app in (PROXY, PROVIDER, consumer):
            with self.subTest(app=app):
                self.assertEqual(
                    _external_roles(app, True, ldap_consumer=consumer),
                    _external_roles(app, False, ldap_consumer=consumer),
                )

    def test_the_proxy_lists_no_provider_overlay_with_the_switch_on(self):
        self.assertNotIn(PROVIDER, _external_roles(PROXY, True))


@_proven()
class TestTheProxyPublishesTheRelayedPorts(unittest.TestCase):
    def test_swarm_with_the_switch_on_publishes_ldaps_in_host_mode(self):
        self.assertEqual(_ports(), [LDAPS])

    def test_every_declared_port_becomes_one_term(self):
        registry = copy.deepcopy(REGISTRY)
        registry["ldap"]["overlay"]["stream_relay"]["ports"] = ["ldaps", "ldap"]
        self.assertEqual(
            _ports(registry=registry), [LDAPS, {**LDAPS, "protocol": "ldap"}]
        )

    def test_compose_publishes_nothing(self):
        self.assertEqual(_ports(mode="compose"), [])

    def test_the_switch_off_publishes_nothing(self):
        self.assertEqual(_ports(public=False), [])

    def test_the_provider_publishes_nothing_although_it_joins(self):
        self.assertEqual(_ports(application_id=PROVIDER), [])
        self.assertEqual(_networks(application_id=PROVIDER), [RELAY_NETWORK])

    def test_another_role_publishes_nothing(self):
        self.assertEqual(_ports(application_id="web-app-nextcloud"), [])

    def test_an_alias_entry_of_the_provider_publishes_nothing_twice(self):
        registry = copy.deepcopy(REGISTRY)
        registry["ldap-alias"] = {
            **copy.deepcopy(registry["ldap"]),
            "canonical": "ldap",
        }
        self.assertEqual(_ports(registry=registry), [LDAPS])
        self.assertEqual(_networks(registry=registry), [RELAY_NETWORK])

    def test_missing_ports_raise(self):
        registry = copy.deepcopy(REGISTRY)
        del registry["ldap"]["overlay"]["stream_relay"]["ports"]
        with self.assertRaisesRegex(ValueError, "stream_relay needs ports"):
            _ports(registry=registry)


@_proven()
class TestTheRelayNetworksToPreCreate(unittest.TestCase):
    def test_the_proxy_pre_creates_the_relay_network(self):
        self.assertEqual(_networks(), [RELAY_NETWORK])

    def test_a_relay_without_a_pinned_subnet_fails_loudly(self):
        registry = copy.deepcopy(REGISTRY)
        del registry["ldap"]["overlay"]["stream_relay"]["subnet"]
        with self.assertRaisesRegex(ValueError, "stream_relay needs a subnet"):
            _networks(registry=registry)

    def test_nothing_to_pre_create_without_the_relay(self):
        for kwargs in (
            {"mode": "compose"},
            {"public": False},
            {"application_id": "web-app-nextcloud"},
        ):
            with self.subTest(**kwargs):
                self.assertEqual(_networks(**kwargs), [])


if __name__ == "__main__":
    unittest.main()
