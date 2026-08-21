import unittest

from jinja2 import Environment, FileSystemLoader

from tests.integration.roles import PROJECT_ROOT


def _render_dnsmasq(**overrides):
    variables = {
        "TOR_DNSMASQ_OWNS_LISTENER": True,
        "TOR_CONTAINER_DNS_HOST": "172.17.0.1",
        "TOR_NODE_ONION": "example.onion",
        "TOR_HS_BACKEND_HOST": "172.17.0.1",
        "TOR_DNS_PORT": 9053,
        "TOR_DNS_UPSTREAMS": ["172.30.0.53"],
    }
    variables.update(overrides)
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        autoescape=False,  # noqa: S701 - dnsmasq config, html escaping would corrupt it
    )
    template = env.get_template("roles/svc-net-tor/templates/dnsmasq-tor-onion.conf.j2")
    return template.render(**variables)


class TestDnsmasqListeners(unittest.TestCase):
    """dnsmasq must answer on the docker bridge as well as on loopback: docker
    discards loopback resolvers, so a 127.0.0.1-only listener never reaches the
    containers that need .onion resolved."""

    def test_listens_on_bridge_in_addition_to_loopback(self):
        rendered = _render_dnsmasq()
        self.assertIn("listen-address=127.0.0.1", rendered)
        self.assertIn("listen-address=172.17.0.1", rendered)

    def test_bridge_listener_omitted_when_unset(self):
        rendered = _render_dnsmasq(TOR_CONTAINER_DNS_HOST="")
        self.assertIn("listen-address=127.0.0.1", rendered)
        self.assertNotIn("listen-address=172.17", rendered)

    def test_no_bind_policy_when_the_listener_is_not_ours(self):
        rendered = _render_dnsmasq(
            TOR_DNSMASQ_OWNS_LISTENER=False, TOR_CONTAINER_DNS_HOST=""
        )
        self.assertNotIn("bind-dynamic", rendered)
        self.assertNotIn("listen-address", rendered)

    def test_onion_queries_go_to_the_tor_resolver(self):
        self.assertIn("server=/onion/127.0.0.1#9053", _render_dnsmasq())

    def test_clearnet_upstreams_are_kept(self):
        self.assertIn("server=172.30.0.53", _render_dnsmasq())

    def test_upstream_policy_stays_off_a_listener_we_do_not_own(self):
        """A shared dnsmasq brings its own upstreams, and in swarm
        networks.internet.dns is the docker bridge that very dnsmasq answers
        on. Writing a server= there points the resolver at itself, and
        no-resolv would cut the upstreams its owner configured."""
        rendered = _render_dnsmasq(TOR_DNSMASQ_OWNS_LISTENER=False)
        self.assertNotIn("server=172.30.0.53", rendered)
        self.assertNotIn("no-resolv", rendered)
        self.assertIn("server=/onion/127.0.0.1#9053", rendered)

    def test_upstream_policy_applies_to_our_own_listener(self):
        rendered = _render_dnsmasq()
        self.assertIn("no-resolv", rendered)
        self.assertIn("server=172.30.0.53", rendered)

    def test_own_onion_resolves_to_a_container_reachable_backend(self):
        self.assertIn("address=/example.onion/172.17.0.1", _render_dnsmasq())


if __name__ == "__main__":
    unittest.main()
