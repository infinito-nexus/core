import sys
import unittest
from typing import ClassVar

from . import PROJECT_ROOT


def _ensure_repo_root_on_syspath():
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))


_ensure_repo_root_on_syspath()

from ansible.errors import AnsibleError  # noqa: E402

from plugins.lookup.container_dns import resolve_container_dns  # noqa: E402
from utils.templating.ansible import (  # noqa: E402
    TrustedAsTemplate,
    _trust_as_template,
)

_POOLS = [{"base": "10.208.0.0/12", "size": 24}]
_PUBLIC = ["192.0.2.53", "198.51.100.53"]
_GATEWAY = "10.208.0.1"

_BRIDGE = {"docker0": {"ipv4": {"address": "172.17.0.1"}}}
_CLEARNET = {"internet": {"dns": "172.30.0.53"}}


def _vars(**overrides):
    """Return play variables for the lookup.

    Args:
        overrides: values replacing the defaults.

    The pools and the public resolvers are group_vars that exist on every host,
    so a fixture without them tests a shape production never has.
    """
    variables = {
        "ansible_facts": _BRIDGE,
        "group_names": ["svc-net-tor"],
        "networks": _CLEARNET,
        "DEPLOYMENT_MODE": "compose",
        "NETWORK_DOCKER_ADDRESS_POOLS": _POOLS,
        "NETWORK_PUBLIC_DNS_RESOLVERS": _PUBLIC,
    }
    variables.update(overrides)
    return variables


class TestResolveContainerDns(unittest.TestCase):
    """The bridge resolver must come first on a Tor node so .onion resolves,
    with the clearnet resolver kept as fallback."""

    def test_tor_node_prefers_the_bridge_resolver(self):
        self.assertEqual(resolve_container_dns(_vars()), [_GATEWAY, "172.30.0.53"])

    def test_without_tor_only_clearnet(self):
        self.assertEqual(resolve_container_dns(_vars(group_names=[])), ["172.30.0.53"])

    def test_the_bridge_follows_ownership_not_the_deploy_mode(self):
        self.assertEqual(
            resolve_container_dns(_vars(DEPLOYMENT_MODE="swarm")),
            [_GATEWAY, "172.30.0.53"],
        )

    def test_a_tor_node_without_clearnet_still_gets_a_second_resolver(self):
        self.assertEqual(
            resolve_container_dns(_vars(DEPLOYMENT_MODE="swarm", networks={})),
            [_GATEWAY, _PUBLIC[0]],
        )

    def test_a_non_tor_node_yields_nothing_without_clearnet(self):
        self.assertEqual(resolve_container_dns(_vars(group_names=[], networks={})), [])

    def test_a_bridge_equal_to_clearnet_is_not_emitted_twice(self):
        self.assertEqual(
            resolve_container_dns(_vars(networks={"internet": {"dns": _GATEWAY}})),
            [_GATEWAY, _PUBLIC[0]],
        )

    def test_the_declaration_answers_where_the_fact_is_absent(self):
        self.assertEqual(
            resolve_container_dns(_vars(ansible_facts={}, group_names=[])),
            ["172.30.0.53"],
        )

    def test_a_pool_less_host_has_no_bridge_to_offer(self):
        self.assertEqual(
            resolve_container_dns(_vars(networks={}, NETWORK_DOCKER_ADDRESS_POOLS=[])),
            [],
        )

    def test_missing_keys_do_not_raise(self):
        self.assertEqual(resolve_container_dns({}), [])


class TestALoopbackResolverIsNotAClaim(unittest.TestCase):
    """Reading resolv.conf cannot tell who binds the bridge.

    A systemd-resolved stub on ``127.0.0.53`` and a node dnsmasq that also
    listens on the bridge look identical from the host's own resolv.conf, and
    only the second is reachable from a container. Treating loopback as proof
    handed ordinary hosts a bridge address nothing served, and their image
    builds resolved nothing while the daemon itself resolved fine.
    """

    @staticmethod
    def _facts(nameservers):
        return {**_BRIDGE, "dns": {"nameservers": nameservers}}

    def _resolve(self, nameservers, **overrides):
        """Return the resolver list for a host with these nameservers.

        Args:
            nameservers: what the host's own resolv.conf lists.
            overrides: further variables, e.g. the bridge declaration.
        """
        return resolve_container_dns(
            _vars(group_names=[], ansible_facts=self._facts(nameservers), **overrides)
        )

    def test_a_loopback_stub_alone_earns_no_bridge(self):
        for nameservers in (["127.0.0.1"], ["127.0.0.53"], ["::1"]):
            with self.subTest(nameservers=nameservers):
                self.assertEqual(["172.30.0.53"], self._resolve(nameservers))

    def test_the_declaration_is_what_earns_it(self):
        self.assertEqual(
            [_GATEWAY, "172.30.0.53"],
            self._resolve(["127.0.0.1"], NETWORK_CONTAINER_BRIDGE_RESOLVER=True),
        )

    def test_a_routable_host_resolver_needs_no_bridge(self):
        self.assertEqual(["172.30.0.53"], self._resolve(["172.30.0.53"]))

    def test_an_empty_nameserver_list_earns_no_bridge(self):
        self.assertEqual(["172.30.0.53"], self._resolve([]))


class _Templar:
    """Renders one expression, the way a play's templar would.

    Ansible 2.19+ renders only strings carrying ``TrustedAsTemplate``, and
    ``str()`` drops that tag. A stub that renders any string passes while
    production returns the expression untouched, so this one refuses an
    untagged string exactly as the real templar does.
    """

    def __init__(self, mapping):
        self.mapping = mapping

    def template(self, text):
        if TrustedAsTemplate is not None and not TrustedAsTemplate.is_tagged_on(text):
            return text
        for name, value in self.mapping.items():
            if str(text).strip() == "{{ " + name + " | first }}":
                return value[0]
        return text


class TestTheBridgeSurvivesTheFirstRun(unittest.TestCase):
    """The run that writes daemon.json is the one with no docker0 fact.

    Facts are gathered at play start and nothing re-gathers them after the
    daemon is installed, so a fresh node renders its daemon config while
    ``ansible_facts.docker0`` is still absent. Deriving the address from the
    fact alone emitted the clearnet resolver on its own, and the inner
    containers then asked a public resolver for a domain only the node dnsmasq
    knows: ``server can't find infinito.example: NXDOMAIN``.
    """

    POOLS: ClassVar[list] = [{"base": "10.208.0.0/12", "size": 24}]

    def facts(self, **extra):
        """Return facts for a host that resolves only through loopback.

        Args:
            extra: additional fact keys, e.g. a ``docker0`` entry.
        """
        return {"dns": {"nameservers": ["127.0.0.1"]}, **extra}

    def test_the_bridge_is_known_before_docker_ever_ran(self):
        self.assertEqual(
            resolve_container_dns(
                _vars(
                    ansible_facts=self.facts(),
                    group_names=[],
                    networks={"internet": {"dns": "192.0.2.1"}},
                    NETWORK_DOCKER_ADDRESS_POOLS=self.POOLS,
                    NETWORK_CONTAINER_BRIDGE_RESOLVER=True,
                )
            ),
            ["10.208.0.1", "192.0.2.1"],
        )

    def test_the_pass_after_docker_renders_the_same_bytes(self):
        """A differing render restarts the runtime under a live stack."""
        before = resolve_container_dns(
            _vars(
                ansible_facts=self.facts(),
                group_names=[],
                networks={"internet": {"dns": "192.0.2.1"}},
                NETWORK_DOCKER_ADDRESS_POOLS=self.POOLS,
            )
        )
        after = resolve_container_dns(
            _vars(
                ansible_facts=self.facts(docker0={"ipv4": {"address": "10.208.0.1"}}),
                group_names=[],
                networks={"internet": {"dns": "192.0.2.1"}},
                NETWORK_DOCKER_ADDRESS_POOLS=self.POOLS,
            )
        )
        self.assertEqual(before, after)

    def test_a_stale_docker0_fact_never_reaches_the_daemon(self):
        """Docker's default bridge, read before the pools moved it.

        Facts are gathered before the daemon config is applied, so ``docker0``
        still holds ``172.17.0.1`` while the pools are about to put the bridge
        at ``10.208.0.1``. A swarm node shipped exactly that mismatch: its
        daemon.json named the address its live interface no longer had, and
        every lookup inside a container went to a dead resolver.
        """
        self.assertEqual(
            resolve_container_dns(
                _vars(
                    ansible_facts=self.facts(
                        docker0={"ipv4": {"address": "172.17.0.1"}}
                    ),
                    group_names=[],
                    networks={"internet": {"dns": "192.0.2.1"}},
                    NETWORK_DOCKER_ADDRESS_POOLS=self.POOLS,
                    NETWORK_CONTAINER_BRIDGE_RESOLVER=True,
                )
            ),
            ["10.208.0.1", "192.0.2.1"],
        )


class TestTheBridgeNeverGoesOutAlone(unittest.TestCase):
    """No host shape may end up with the bridge as its only resolver.

    Whether anything answers on the bridge is not knowable from the host's own
    resolv.conf: a systemd-resolved stub and a node dnsmasq both read as
    loopback-only and only the second binds the bridge. A list holding just
    that address therefore hands the daemon one possibly-dead nameserver, and
    every container and image build loses DNS - measured as an apk install
    failing on ``DNS: transient error`` with ``"dns": ["10.208.0.1"]``.

    The assertion runs over a cross-product because the regression slipped
    through a suite that checked each shape on its own.
    """

    NAMESERVERS: ClassVar[list] = [
        ["127.0.0.1"],
        ["127.0.0.53"],
        ["::1"],
        ["172.30.0.53"],
        [],
    ]

    def test_every_host_shape_keeps_a_second_resolver(self):
        for nameservers in self.NAMESERVERS:
            for tor in ([], ["svc-net-tor"]):
                for clearnet in ("", "192.0.2.1"):
                    for docker0 in (
                        {},
                        {"docker0": {"ipv4": {"address": "172.17.0.1"}}},
                    ):
                        with self.subTest(
                            nameservers=nameservers, tor=bool(tor), clearnet=clearnet
                        ):
                            result = resolve_container_dns(
                                _vars(
                                    group_names=tor,
                                    networks={"internet": {"dns": clearnet}},
                                    ansible_facts={
                                        "dns": {"nameservers": nameservers},
                                        **docker0,
                                    },
                                )
                            )
                            self.assertNotEqual([_GATEWAY], result)

    def test_the_fallback_is_the_declared_resolver_not_a_literal(self):
        """A hardcoded address here would bypass the project's own SPOT."""
        result = resolve_container_dns(
            _vars(group_names=["svc-net-tor"], networks={"internet": {"dns": ""}})
        )
        self.assertEqual([_GATEWAY, _PUBLIC[0]], result)

    def test_an_empty_resolver_declaration_fails_loudly(self):
        with self.assertRaises(AnsibleError):
            resolve_container_dns(
                _vars(
                    group_names=["svc-net-tor"],
                    networks={"internet": {"dns": ""}},
                    NETWORK_PUBLIC_DNS_RESOLVERS=[],
                )
            )


class TestTheTrustTagIsStillWhereBothSidesLookForIt(unittest.TestCase):
    """Without this the whole class below can pass while production is broken.

    ``_trust_as_template`` and the stub both key off the same private ansible
    module. Were it to move, the tagging degrades to a no-op and the templar
    stops rendering, while the stub degrades to rendering anything and keeps
    the tests green. This asserts the shared premise instead.
    """

    def test_the_tag_class_is_importable(self):
        self.assertIsNotNone(
            TrustedAsTemplate,
            "ansible no longer exposes TrustedAsTemplate where "
            "utils.templating.ansible looks for it; every lookup that "
            "re-tags before templating silently stopped rendering",
        )

    def test_tagging_is_observable(self):
        tagged = _trust_as_template("{{ x }}")
        self.assertTrue(TrustedAsTemplate.is_tagged_on(tagged))
        self.assertFalse(TrustedAsTemplate.is_tagged_on(str(tagged)))


class TestInventoryExpressionIsRendered(unittest.TestCase):
    """The field arrives through `-e @inventory.yml` and is read raw.

    While it held a literal address nobody noticed that nothing rendered it.
    An expression there reached the daemon as its own source text, and docker
    refused the whole config: ParseAddr("{{ ... }}"): unable to parse IP.
    """

    EXPRESSION = "{{ NETWORK_PUBLIC_DNS_RESOLVERS | first }}"

    def facts(self, nameservers):
        return {"dns": {"nameservers": nameservers}, "docker0": {"ipv4": {}}}

    def test_an_expression_is_resolved_against_the_play(self):
        templar = _Templar({"NETWORK_PUBLIC_DNS_RESOLVERS": ["192.0.2.1", "192.0.2.2"]})
        result = resolve_container_dns(
            {
                "networks": {"internet": {"dns": self.EXPRESSION}},
                "group_names": [],
                "ansible_facts": self.facts(["192.0.2.9"]),
            },
            templar,
        )
        self.assertEqual(["192.0.2.1"], result)

    def test_no_resolver_ever_carries_jinja(self):
        """What reaches daemon.json must be an address, not its source text."""
        templar = _Templar({"NETWORK_PUBLIC_DNS_RESOLVERS": ["192.0.2.1"]})
        for nameservers in ([], ["127.0.0.1"], ["192.0.2.9"]):
            with self.subTest(nameservers=nameservers):
                for resolver in resolve_container_dns(
                    {
                        "networks": {"internet": {"dns": self.EXPRESSION}},
                        "group_names": [],
                        "ansible_facts": self.facts(nameservers),
                    },
                    templar,
                ):
                    self.assertNotIn("{{", resolver)

    def test_a_literal_survives_without_a_templar(self):
        """Outside a play there is nothing to render against, and no need."""
        self.assertEqual(
            ["172.30.0.53"],
            resolve_container_dns(
                {
                    "networks": {"internet": {"dns": "172.30.0.53"}},
                    "group_names": [],
                    "ansible_facts": self.facts(["192.0.2.9"]),
                }
            ),
        )

    def test_an_unresolvable_expression_aborts_instead_of_reaching_docker(self):
        """This is the shape that reached CI: no templar, so nothing rendered."""
        with self.assertRaises(AnsibleError) as caught:
            resolve_container_dns(
                {
                    "networks": {"internet": {"dns": self.EXPRESSION}},
                    "group_names": [],
                    "ansible_facts": self.facts(["192.0.2.9"]),
                }
            )
        self.assertIn("daemon.json", str(caught.exception))

    def test_a_templar_that_cannot_resolve_it_aborts_too(self):
        with self.assertRaises(AnsibleError):
            resolve_container_dns(
                {
                    "networks": {"internet": {"dns": self.EXPRESSION}},
                    "group_names": [],
                    "ansible_facts": self.facts(["192.0.2.9"]),
                },
                _Templar({}),
            )


if __name__ == "__main__":
    unittest.main()
