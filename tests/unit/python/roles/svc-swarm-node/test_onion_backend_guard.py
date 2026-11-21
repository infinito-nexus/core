"""The swarm node baseline drop of the ports the node onion reaches through a host-mode publish.

In swarm ``container_ports`` publishes an onion-forwarded ``ports.local`` port in
``mode: host``, which binds every address of the node. The hidden service dials
it from the host network, so its packets never pass prerouting, while every
packet from another host does, before Docker's DNAT rewrites the port. Right
after placement the constructor evaluates the port list once, on the stack
host, and loads the drop from it before the first stack of the run deploys.
"""

from __future__ import annotations

import unittest
import unittest.mock as mock

import jinja2
from ansible.errors import AnsibleFilterError
from jinja2.nativetypes import NativeEnvironment

from plugins.filter.swarm_ingress_guard import FilterModule as SwarmIngressGuard
from plugins.lookup import tor_ports
from plugins.lookup.container_ports import LookupModule as ContainerPorts
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "svc-swarm-node"
TEMPLATE = ROLE / "templates" / "nftables.conf.j2"
REFRESH = ROLE / "tasks" / "utils" / "ingress_guard" / "refresh.yml"
JOIN = ROLE / "tasks" / "00_core" / "ingress_guard.yml"
TOR_TEMPLATE = PROJECT_ROOT / "roles" / "svc-net-tor" / "templates" / "nftables.conf.j2"
CONSTRUCTOR = load_yaml_any(
    str(PROJECT_ROOT / "tasks" / "stages" / "01_constructor.yml")
)
EVALUATION_INCLUDE = "./tasks/utils/constructor/onion_backends.yml"
EVALUATION = load_yaml_any(str(PROJECT_ROOT / EVALUATION_INCLUDE))
SWARM = load_yaml_any(str(PROJECT_ROOT / "group_vars" / "all" / "18_swarm.yml"))
DROP = 'iifname != "lo" fib daddr type local tcp dport @onion_backends_tcp drop'
STACK_HOST = "mgr-01"
DEPLOYED = ["svc-db-mariadb", "svc-db-openldap", "web-app-gitea"]
GROUPS = {"wrk-01": ["svc-swarm-node"], STACK_HOST: [*DEPLOYED, "svc-net-tor"]}


def applications(tor: bool = True) -> dict:
    """
    Args:
        tor: whether svc-net-tor is deployed for the two databases.

    Returns:
        An applications view with an exposed MariaDB and OpenLDAP and a Gitea
        that forwards nothing.
    """
    return {
        "svc-db-mariadb": {
            "services": {
                "tor": {"enabled": tor},
                "mariadb": {
                    "exposed": True,
                    "ports": {
                        "local": {"mariadb": 3306},
                        "internal": {"mariadb": 3306},
                    },
                },
            }
        },
        "svc-db-openldap": {
            "services": {
                "tor": {"enabled": tor},
                "openldap": {
                    "exposed": True,
                    "ports": {
                        "local": {"ldap": 389},
                        "internal": {"ldap": 389},
                        "public": {"ldaps": 636},
                    },
                },
            }
        },
        "web-app-gitea": {
            "services": {
                "tor": {"enabled": True},
                "gitea": {
                    "ports": {"local": {"http": 8002}, "internal": {"http": 3000}}
                },
            }
        },
    }


def host_lookup(host: str):
    """
    Args:
        host: the play host whose variables the lookup renders with.

    Returns:
        ``lookup`` as Ansible calls it on *host*: the applications view that
        host renders, whose ``services.tor.enabled`` is ``'svc-net-tor' in
        group_names``, and the real ``tor_ports`` over it.
    """
    group_names = GROUPS[host]

    def lookup(name: str, *terms: object, **kwargs: object) -> object:
        view = applications("svc-net-tor" in group_names)
        if name == "applications":
            return view
        if name != "tor_ports":
            raise AssertionError(f"unexpected lookup {name!r}")
        with mock.patch.object(tor_ports, "lookup_loader") as loader:
            loader.get.return_value = mock.MagicMock(run=lambda *_a, **_k: [view])
            return tor_ports.LookupModule().run(
                list(terms), variables={"group_names": group_names}, **kwargs
            )[0]

    return lookup


def evaluate_task() -> dict:
    (task,) = [
        task
        for task in EVALUATION
        if "swarm_onion_host_backends" in (task.get("ansible.builtin.set_fact") or {})
    ]
    return task


def run_constructor(order: list[str]) -> dict[str, dict]:
    """
    Args:
        order: the play hosts in the order the evaluation task reaches them.

    Returns:
        Per host the facts the constructor's evaluation task leaves behind.
    """
    task = evaluate_task()
    environment = NativeEnvironment(undefined=jinja2.StrictUndefined)
    environment.filters["bool"] = bool
    facts: dict[str, dict] = {host: {} for host in order}
    for host in order:
        scope = {
            "IS_SWARM_MODE": True,
            "STACK_HOST": STACK_HOST,
            "inventory_hostname": host,
        }
        if all(
            environment.from_string("{{ " + condition + " }}").render(scope)
            for condition in task["when"]
        ):
            facts[host]["swarm_onion_host_backends"] = environment.from_string(
                task["ansible.builtin.set_fact"]["swarm_onion_host_backends"]
            ).render(lookup=host_lookup(host))
    return facts


def backends_on(host: str, facts: dict[str, dict]) -> list[dict]:
    """
    Args:
        host: the play host that renders ``SWARM_ONION_HOST_BACKENDS``.
        facts: per host the facts the play holds.

    Returns:
        ``SWARM_ONION_HOST_BACKENDS`` as ``group_vars/all/18_swarm.yml``
        evaluates it on *host*.
    """
    environment = NativeEnvironment(undefined=jinja2.StrictUndefined)
    return environment.from_string(SWARM["SWARM_ONION_HOST_BACKENDS"]).render(
        lookup=host_lookup(host),
        STACK_HOST=STACK_HOST,
        group_names=GROUPS[host],
        hostvars={
            name: {**facts.get(name, {}), "group_names": groups}
            for name, groups in GROUPS.items()
        },
    )


def guarded_on(host: str, facts: dict[str, dict]) -> list[int]:
    """
    Args:
        host: the play host that renders ``SWARM_ONION_GUARDED``.
        facts: per host the facts the play holds.

    Returns:
        ``SWARM_ONION_GUARDED`` as ``group_vars/all/18_swarm.yml`` evaluates it
        on *host* while no service publishes anything yet.
    """
    environment = NativeEnvironment(undefined=jinja2.StrictUndefined)
    environment.filters.update(SwarmIngressGuard().filters())
    return environment.from_string(SWARM["SWARM_ONION_GUARDED"]).render(
        lookup=host_lookup(host),
        SWARM_ONION_HOST_BACKENDS=backends_on(host, facts),
        swarm_ingress_read={"stdout_lines": []},
    )


def ruleset(ports: list[int]) -> str:
    """
    Args:
        ports: the ``SWARM_ONION_GUARDED_PORTS`` the baseline renders.

    Returns:
        The rendered nft table of the swarm node baseline.
    """
    environment = jinja2.Environment(
        keep_trailing_newline=True,
        trim_blocks=True,
        undefined=jinja2.StrictUndefined,
        autoescape=jinja2.select_autoescape(default_for_string=False),
    )
    return environment.from_string(read_text(str(TEMPLATE))).render(
        FIREWALL_TABLE="infinito_svc_swarm_node",
        SWARM_INGRESS_GUARDED_PORTS=[{"protocol": "tcp", "port": 5432}],
        SWARM_INGRESS_PEER_ADDRESSES={"ipv4": ["10.0.0.2"], "ipv6": []},
        SWARM_ONION_GUARDED_PORTS=ports,
    )


def chain_of(rendered: str, rule: str) -> list[str]:
    """
    Args:
        rendered: an nft table.
        rule: a rule line of one of its chains.

    Returns:
        The lines of the chain that holds *rule*, hook line included.
    """
    lines = [line.strip() for line in rendered.splitlines()]
    position = lines.index(rule)
    start = max(i for i in range(position) if lines[i].startswith("chain "))
    end = lines.index("}", position)
    return lines[start:end]


def published_in_host_mode(view: dict, backends: list[dict]) -> list[int]:
    """
    Args:
        view: the applications view ``container_ports`` reads.
        backends: the ``SWARM_ONION_HOST_BACKENDS`` the play holds.

    Returns:
        Every port ``container_ports`` publishes in ``mode: host`` in swarm for
        a loopback-bound term of each ``ports.local`` category of *view*.
    """
    lookup = ContainerPorts()
    lookup._loader = mock.MagicMock()
    ports: set[int] = set()
    with mock.patch("plugins.lookup.container_ports.lookup_loader") as loader:
        loader.get.return_value = mock.MagicMock(run=lambda *_a, **_k: [view])
        for app_id, config in view.items():
            for service, entity in config["services"].items():
                for category in entity.get("ports", {}).get("local", {}):
                    block = lookup.run(
                        [[service, category, "127.0.0.1"]],
                        variables={
                            "application_id": app_id,
                            "DEPLOYMENT_MODE": "swarm",
                            "SWARM_ONION_HOST_BACKENDS": backends,
                        },
                    )[0]
                    if "mode: host" in block:
                        ports.update(
                            int(line.split(":", 1)[1])
                            for line in block.splitlines()
                            if line.strip().startswith("published:")
                        )
    return sorted(ports)


def ports_of(entries: list[dict]) -> list[int]:
    return sorted(entry["port"] for entry in entries)


class TestOnionBackendBaselineGuard(unittest.TestCase):
    def test_the_baseline_drops_every_outside_packet_to_an_onion_backend(self) -> None:
        rendered = ruleset(guarded_on("wrk-01", run_constructor(list(GROUPS))))
        self.assertIn("elements = { 389, 3306 }", rendered)
        self.assertIn(DROP, chain_of(rendered, DROP))

    def test_the_drop_runs_before_docker_rewrites_the_port(self) -> None:
        rendered = ruleset(guarded_on("wrk-01", run_constructor(list(GROUPS))))
        self.assertIn(
            "type filter hook prerouting priority -150; policy accept;",
            chain_of(rendered, DROP),
        )

    def test_swarm_peers_and_containers_get_no_exemption(self) -> None:
        self.assertNotIn("peers", DROP)
        self.assertNotIn("docker", DROP)

    def test_the_list_is_evaluated_once_on_the_stack_host(self) -> None:
        facts = run_constructor(list(GROUPS))
        self.assertEqual([host for host, held in facts.items() if held], [STACK_HOST])
        self.assertEqual(
            ports_of(facts[STACK_HOST]["swarm_onion_host_backends"]), [389, 3306]
        )

    def test_a_worker_that_renders_first_reads_the_stack_host_set(self) -> None:
        facts = {
            STACK_HOST: {
                "swarm_onion_host_backends": tor_ports.collect_host_mode_backends(
                    applications(), DEPLOYED
                )
            }
        }
        for host in GROUPS:
            with self.subTest(host=host):
                self.assertEqual(ports_of(backends_on(host, facts)), [389, 3306])

    def test_a_missing_list_fails_instead_of_emptying_the_drop(self) -> None:
        with self.assertRaises(AnsibleFilterError):
            ruleset(guarded_on("wrk-01", {}))

    def test_without_tor_nothing_extra_renders(self) -> None:
        self.assertEqual(
            tor_ports.collect_host_mode_backends(applications(tor=False), DEPLOYED),
            [],
        )
        self.assertNotIn("onion_backends_tcp", ruleset([]))

    def test_without_an_onion_forwarded_port_nothing_extra_renders(self) -> None:
        self.assertEqual(
            tor_ports.collect_host_mode_backends(applications(), ["web-app-gitea"]),
            [],
        )

    def test_the_ports_are_the_ports_published_in_host_mode(self) -> None:
        for tor in (True, False):
            with self.subTest(tor=tor):
                listed = tor_ports.collect_host_mode_backends(
                    applications(tor), DEPLOYED
                )
                self.assertEqual(
                    ports_of(listed),
                    published_in_host_mode(applications(tor), listed),
                )

    def test_a_changed_port_set_reloads_every_node(self) -> None:
        (task,) = [
            task
            for task in load_yaml_any(str(REFRESH))
            if "swarm_ingress_guard_digest"
            in (task.get("ansible.builtin.set_fact") or {})
        ]
        digest = task["ansible.builtin.set_fact"]["swarm_ingress_guard_digest"]
        self.assertIn("SWARM_ONION_GUARDED", digest)

    def test_the_baseline_loads_when_the_node_joins(self) -> None:
        (task,) = [
            task
            for task in load_yaml_any(str(JOIN))
            if (task.get("ansible.builtin.include_role") or {}).get("name")
            == "svc-net-firewall"
        ]
        self.assertEqual(task["vars"]["FIREWALL_FRAGMENT_ROLE"], "svc-swarm-node")

    def test_the_drop_loads_before_the_first_stack_of_the_run_deploys(self) -> None:
        def position(predicate) -> int:
            return next(i for i, task in enumerate(CONSTRUCTOR) if predicate(task))

        evaluate = position(
            lambda task: task.get("ansible.builtin.include_tasks") == EVALUATION_INCLUDE
        )
        join = position(
            lambda task: (
                (task.get("ansible.builtin.include_role") or {}).get("name")
                == "svc-swarm-node"
            )
        )
        reload = position(
            lambda task: (
                "ingress_guard/refresh.yml"
                in str(task.get("ansible.builtin.include_tasks", ""))
            )
        )
        first_stack = position(
            lambda task: str(task.get("ansible.builtin.include_tasks", "")).endswith(
                "tasks/utils/setup/group.yml"
            )
        )
        self.assertLess(evaluate, join)
        self.assertLess(join, reload)
        self.assertLess(reload, first_stack)

    def test_a_deploy_that_skips_svc_swarm_node_still_loads_the_drop(self) -> None:
        (task,) = [
            task
            for task in CONSTRUCTOR
            if "ingress_guard/refresh.yml"
            in str(task.get("ansible.builtin.include_tasks", ""))
        ]
        self.assertEqual(
            task["when"],
            ["IS_SWARM_MODE | bool", "run_once_svc_swarm_node is not defined"],
        )

    def test_svc_net_tor_carries_no_second_copy(self) -> None:
        torrc_table = read_text(str(TOR_TEMPLATE))
        self.assertNotIn("ct original", torrc_table)
        self.assertNotIn("ONION_HOST", torrc_table)

    def test_the_host_mode_lookup_fails_closed_without_the_applications(self) -> None:
        with mock.patch.object(tor_ports, "lookup_loader") as loader:
            loader.get.return_value = mock.MagicMock(
                run=mock.MagicMock(side_effect=RuntimeError("no merged view"))
            )
            with self.assertRaises(RuntimeError):
                tor_ports.LookupModule().run(
                    [], variables={"group_names": DEPLOYED}, host_mode=True
                )


if __name__ == "__main__":
    unittest.main()
