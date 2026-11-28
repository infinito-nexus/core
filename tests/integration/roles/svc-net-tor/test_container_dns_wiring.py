import unittest
import unittest.mock as mock

from ansible.module_utils.parsing.convert_bool import boolean as ansible_boolean
from jinja2 import Environment, FileSystemLoader, select_autoescape

from plugins.lookup import container_dns
from tests.integration.roles import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.networks.tor_egress import plan as tor_egress_plan

ROUTER = PROJECT_ROOT / "roles/svc-net-tor/tasks/router.yml"
CORE = PROJECT_ROOT / "roles/svc-net-tor/tasks/00_core.yml"
ROLE_FILES = PROJECT_ROOT / "roles/svc-net-tor/files"
RESOLV_TASK = "🔀 Egress router | Point the host resolver at dnsmasq (127.0.0.1)"
DROPIN_BLOCK = "🔁 Egress router | Retry dnsmasq until docker0 exists after a boot"
START_TASK = "🚀 Egress router | Enable + (re)start dnsmasq"
REGATHER_TASK = (
    "📊 Re-gather every node's docker0 fact so torrc and dnsmasq bind the live bridge"
)
TOR_NODE_VARIABLES = {
    "group_names": ["svc-net-tor"],
    "NETWORK_DOCKER_ADDRESS_POOLS": [{"base": "10.208.0.0/12", "size": 24}],
    "NETWORK_PUBLIC_DNS_RESOLVERS": ["9.9.9.9"],
    "networks": {"internet": {"dns": "172.30.0.53"}},
}


def _walk(tasks):
    for task in tasks or []:
        yield task
        for section in ("block", "rescue", "always"):
            yield from _walk(task.get(section))


def _render_dnsmasq(**overrides):
    variables = {
        "TOR_DNSMASQ_OWNS_LISTENER": True,
        "TOR_CONTAINER_DNS_HOST": "172.17.0.1",
        "TOR_NODE_ONION": "example.onion",
        "TOR_HS_BACKEND_HOST": "172.17.0.1",
        "TOR_DNS_PORT": 9053,
        "TOR_DNS_UPSTREAMS": ["172.30.0.53"],
        "TOR_EGRESS_ROUTE": "onion",
        "TOR_EGRESS_PLAN": tor_egress_plan(
            {
                "tor": {"include": [], "except": []},
                "direct": {"include": [], "except": []},
            },
            "onion",
        ),
    }
    variables.update(overrides)
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        autoescape=select_autoescape(),
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

    def test_loopback_only_binds_statically(self):
        """A loopback-only listener has no address to wait for, and the rebuild
        that bind-dynamic performs on every netlink event can then only drop it."""
        rendered = _render_dnsmasq(TOR_CONTAINER_DNS_HOST="")
        self.assertIn("bind-interfaces", rendered)
        self.assertNotIn("bind-dynamic", rendered)

    def test_the_static_bind_claims_no_address_it_was_not_given(self):
        """interface= and listen-address= are a union in dnsmasq, so naming lo
        would additionally seize 127.0.0.53 and ::1, where a distro stub sits."""
        rendered = _render_dnsmasq(TOR_CONTAINER_DNS_HOST="")
        self.assertNotIn("interface=", rendered)

    def test_a_bridge_listener_binds_statically_too(self):
        rendered = _render_dnsmasq()
        self.assertIn(
            "bind-interfaces",
            rendered,
            "bind-dynamic closes every listener a failed netlink re-enumeration did "
            "not re-find, loopback included, and nothing reopens them until the "
            "next address event",
        )
        self.assertNotIn("bind-dynamic", rendered)

    def test_no_bind_policy_when_the_listener_is_not_ours(self):
        rendered = _render_dnsmasq(
            TOR_DNSMASQ_OWNS_LISTENER=False, TOR_CONTAINER_DNS_HOST=""
        )
        self.assertNotIn("bind-dynamic", rendered)
        self.assertNotIn("bind-interfaces", rendered)
        self.assertNotIn("listen-address", rendered)

    def test_onion_queries_go_to_the_tor_resolver(self):
        self.assertIn("server=/onion/127.0.0.1#9053", _render_dnsmasq())

    def test_clearnet_upstreams_are_kept(self):
        self.assertIn("server=172.30.0.53", _render_dnsmasq())

    def test_upstream_policy_stays_off_a_listener_we_do_not_own(self):
        """A shared dnsmasq brings its own upstreams, chosen by whoever set it
        up. Writing our server= into it overrides that choice, and no-resolv
        would cut the upstreams its owner configured."""
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


class TestStaticBindSurvivesBoot(unittest.TestCase):
    def _router_tasks(self):
        return list(_walk(load_yaml_str(read_text(str(ROUTER)))))

    def test_dnsmasq_retries_until_its_addresses_exist(self):
        tasks = self._router_tasks()
        block = next(t for t in tasks if t.get("name") == DROPIN_BLOCK)
        self.assertEqual(
            block["when"],
            "TOR_DNSMASQ_OWNS_LISTENER | bool",
            "a shared dnsmasq keeps the unit its owner configured",
        )
        src = next(
            t["ansible.builtin.copy"]["src"]
            for t in _walk(block["block"])
            if "ansible.builtin.copy" in t
        )
        dropin = read_text(str(ROLE_FILES / src))
        self.assertIn(
            "Restart=on-failure",
            dropin.splitlines(),
            "docker.service orders after nss-lookup.target, which dnsmasq precedes, "
            "so a static bind on docker0 fails once per boot and must be retried",
        )

    def test_a_changed_dropin_is_loaded_before_dnsmasq_starts(self):
        tasks = self._router_tasks()
        names = [t.get("name") for t in tasks]
        start = next(t for t in tasks if t.get("name") == START_TASK)
        self.assertLess(names.index(DROPIN_BLOCK), names.index(START_TASK))

        reload_expression = start["ansible.builtin.systemd"]["daemon_reload"]
        env = Environment(autoescape=select_autoescape(default_for_string=False))
        env.filters["bool"] = ansible_boolean
        env.tests["changed"] = lambda result: bool(result.get("changed", False))

        self.assertEqual(
            env.from_string(reload_expression).render(
                TOR_DNSMASQ_OWNS_LISTENER=True, _tor_dnsmasq_dropin={"changed": True}
            ),
            "True",
            "a rewritten drop-in has to reach systemd before the unit restarts",
        )
        self.assertEqual(
            env.from_string(reload_expression).render(TOR_DNSMASQ_OWNS_LISTENER=False),
            "False",
            "the drop-in task is gated on owning the listener, so the reload "
            "expression must not reach for its register when it was skipped",
        )

    def test_the_bridge_fact_is_live_before_anything_binds_it(self):
        tasks = list(_walk(load_yaml_str(read_text(str(CORE)))))
        names = [t.get("name") for t in tasks]
        regather = next(t for t in tasks if t.get("name") == REGATHER_TASK)
        self.assertEqual(
            regather["ansible.builtin.setup"]["filter"],
            ["ansible_docker0"],
            "the play-start docker0 fact predates default-address-pools moving the "
            "bridge, and a static bind on the stale address makes dnsmasq exit",
        )
        self.assertEqual(regather["delegate_to"], "{{ item }}")
        self.assertIs(regather["delegate_facts"], True)
        self.assertLess(
            names.index(REGATHER_TASK), names.index("📝 Render the torrc of every node")
        )
        self.assertLess(
            names.index(REGATHER_TASK),
            names.index("🧅 Wire the host-level transparent .onion egress router"),
        )


class TestHostResolver(unittest.TestCase):
    """glibc reads resolv.conf per query and keeps no server state, so the
    clearnet entry costs nothing while dnsmasq answers and carries the host when
    it stops. systemd-resolved does keep state, which is why the role has to
    stay out of its way rather than drop the entry."""

    def _resolv_conf(self, route: str) -> str:
        tasks = _walk(load_yaml_str(read_text(str(ROUTER))))
        task = next(t for t in tasks if t.get("name") == RESOLV_TASK)
        env = Environment(
            loader=FileSystemLoader(str(PROJECT_ROOT)),
            autoescape=select_autoescape(),
        )
        template = env.get_template(
            f"roles/svc-net-tor/templates/{task['ansible.builtin.template']['src']}"
        )
        return template.render(
            networks={"internet": {"dns": "172.30.0.53"}}, TOR_EGRESS_ROUTE=route
        )

    def _servers(self, route: str) -> list[str]:
        return [
            line.split()[1]
            for line in self._resolv_conf(route).splitlines()
            if line.startswith("nameserver ")
        ]

    def test_dnsmasq_answers_first_and_the_upstream_carries_the_host(self):
        servers = self._servers("onion")
        self.assertEqual(len(servers), 2)
        self.assertEqual(servers[0], "127.0.0.1")

    def test_route_all_leaves_the_host_no_clearnet_fallback(self):
        self.assertEqual(self._servers("all"), ["127.0.0.1"])


class TestContainerResolversUnderRouteAll(unittest.TestCase):
    """Docker moves to the next nameserver whenever dnsmasq answers SERVFAIL,
    which is what it answers while Tor is down. Under route all the bridge must
    therefore be the only resolver containers get, or a stopped Tor turns into
    clearnet DNS for every container."""

    def _daemon_dns(self, route: str) -> list[str]:
        lookup = container_dns.LookupModule()
        with mock.patch.object(container_dns, "lookup_loader") as loader:
            loader.get.return_value = mock.MagicMock(
                run=mock.MagicMock(return_value=[route])
            )
            emitted = lookup.run([], variables=dict(TOR_NODE_VARIABLES))[0]
        self.assertEqual(
            loader.get.return_value.run.call_args.args[0],
            ["svc-net-tor", "services.tor.egress.route"],
        )
        return emitted

    def test_route_all_hands_containers_only_the_bridge(self):
        self.assertEqual(self._daemon_dns("all"), ["10.208.0.1"])

    def test_route_onion_keeps_the_clearnet_second_entry(self):
        self.assertEqual(self._daemon_dns("onion"), ["10.208.0.1", "172.30.0.53"])

    def test_off_a_tor_node_the_route_is_never_read(self):
        with mock.patch.object(container_dns, "lookup_loader") as loader:
            self.assertEqual(
                container_dns.tor_route({"group_names": []}, None, None), ""
            )
        loader.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
