import ipaddress
import re
import unittest

from ansible.errors import AnsibleFilterError

from plugins.filter.swarm_ingress_guard import (
    FilterModule,
    swarm_ingress_guarded,
    swarm_ingress_published,
    swarm_ingress_sections,
    swarm_node_addresses,
    swarm_public_ports,
)
from utils import PROJECT_ROOT
from utils.cache.files import read_text

READ_TASK = PROJECT_ROOT / "roles/svc-swarm-node/tasks/utils/ingress_guard/read.yml"


class TestSwarmIngressSections(unittest.TestCase):
    def test_the_read_task_prints_exactly_the_tags_the_filter_splits(self):
        tags = set(re.findall(r"--format '(\w+) ", read_text(str(READ_TASK))))
        self.assertEqual(tags, set(swarm_ingress_sections([])))

    def test_splits_the_one_read_into_service_and_node_lines(self):
        ports = '[{"Protocol":"tcp","TargetPort":5432,"PublishedPort":5432,"PublishMode":"ingress"}]'
        lines = [
            f"port {ports}",
            "port null",
            "",
            "node 10.0.0.7",
            "node fd00::2",
        ]
        self.assertEqual(
            swarm_ingress_sections(lines),
            {"port": [ports, "null"], "node": ["10.0.0.7", "fd00::2"]},
        )

    def test_feeds_the_published_and_address_filters_unchanged(self):
        ports = '[{"Protocol":"udp","TargetPort":3478,"PublishedPort":3478,"PublishMode":"ingress"}]'
        sections = swarm_ingress_sections([f"port {ports}", "node 10.0.0.3"])
        self.assertEqual(
            swarm_ingress_published(sections["port"]),
            swarm_ingress_published([ports]),
        )
        self.assertEqual(
            swarm_node_addresses(sections["node"]),
            swarm_node_addresses(["10.0.0.3"]),
        )

    def test_a_node_without_an_address_yields_no_peer(self):
        sections = swarm_ingress_sections(["node"])
        self.assertEqual(sections, {"port": [], "node": [""]})
        self.assertEqual(
            swarm_node_addresses(sections["node"]), {"ipv4": [], "ipv6": []}
        )

    def test_no_output_means_empty_sections(self):
        self.assertEqual(swarm_ingress_sections([]), {"port": [], "node": []})

    def test_refuses_an_untagged_line(self):
        with self.assertRaises(AnsibleFilterError):
            swarm_ingress_sections(["Error: This node is not a swarm manager."])

    def test_a_tagged_line_that_is_not_json_still_fails_downstream(self):
        sections = swarm_ingress_sections(["port Error: no such service"])
        with self.assertRaises(AnsibleFilterError):
            swarm_ingress_published(sections["port"])


class TestSwarmIngressPublished(unittest.TestCase):
    def test_keeps_ingress_entries_only(self):
        lines = [
            '[{"Protocol":"tcp","TargetPort":5432,"PublishedPort":5432,"PublishMode":"ingress"}]',
            '[{"Protocol":"tcp","TargetPort":80,"PublishedPort":80,"PublishMode":"host"}]',
            "null",
            (
                '[{"Protocol":"udp","TargetPort":3478,"PublishedPort":3478,"PublishMode":"ingress"},'
                '{"Protocol":"tcp","TargetPort":5000,"PublishedPort":30001,"PublishMode":"ingress"}]'
            ),
        ]
        self.assertEqual(
            swarm_ingress_published(lines),
            [
                {"protocol": "tcp", "port": 5432},
                {"protocol": "tcp", "port": 30001},
                {"protocol": "udp", "port": 3478},
            ],
        )

    def test_a_port_two_services_publish_appears_once(self):
        line = '[{"Protocol":"tcp","TargetPort":1,"PublishedPort":8080,"PublishMode":"ingress"}]'
        self.assertEqual(
            swarm_ingress_published([line, line]),
            [{"protocol": "tcp", "port": 8080}],
        )

    def test_no_output_means_no_published_port(self):
        self.assertEqual(swarm_ingress_published([]), [])

    def test_refuses_a_line_that_is_not_json(self):
        with self.assertRaises(AnsibleFilterError):
            swarm_ingress_published(["Error: no such service"])

    def test_refuses_an_unknown_protocol(self):
        line = '[{"Protocol":"sctp","TargetPort":1,"PublishedPort":9,"PublishMode":"ingress"}]'
        with self.assertRaises(AnsibleFilterError):
            swarm_ingress_published([line])


class TestSwarmPublicPorts(unittest.TestCase):
    def test_collects_single_ports_and_expands_ranges(self):
        applications = {
            "web-app-gitea": {
                "services": {"gitea": {"ports": {"public": {"ssh": 2201}}}}
            },
            "web-svc-coturn": {
                "services": {
                    "coturn": {
                        "ports": {
                            "public": {
                                "stun_turn": 3478,
                                "relay": {"start": 49160, "end": 49162},
                            }
                        }
                    }
                }
            },
            "web-app-moodle": {
                "services": {"moodle": {"ports": {"local": {"http": 8033}}}}
            },
            "svc-empty": {"services": None},
        }
        self.assertEqual(
            swarm_public_ports(applications),
            [2201, 3478, 49160, 49161, 49162],
        )


class TestSwarmIngressGuarded(unittest.TestCase):
    def test_drops_the_ports_declared_public(self):
        published = [
            {"protocol": "tcp", "port": 2201},
            {"protocol": "tcp", "port": 5432},
            {"protocol": "udp", "port": 3478},
            {"protocol": "tcp", "port": 30001},
        ]
        self.assertEqual(
            swarm_ingress_guarded(published, [2201, 3478]),
            [{"protocol": "tcp", "port": 5432}, {"protocol": "tcp", "port": 30001}],
        )


class TestSwarmNodeAddresses(unittest.TestCase):
    def test_splits_by_family_and_drops_the_unspecified_address(self):
        unspecified = str(ipaddress.IPv4Address(0))
        lines = ["10.0.0.7", unspecified, "fd00::2", "10.0.0.3", "", "10.0.0.7"]
        self.assertEqual(
            swarm_node_addresses(lines),
            {"ipv4": ["10.0.0.3", "10.0.0.7"], "ipv6": ["fd00::2"]},
        )

    def test_no_output_means_no_peer(self):
        self.assertEqual(swarm_node_addresses([]), {"ipv4": [], "ipv6": []})

    def test_refuses_a_line_that_is_not_an_address(self):
        with self.assertRaises(AnsibleFilterError):
            swarm_node_addresses(["Error: This node is not a swarm manager."])


class TestFilterModule(unittest.TestCase):
    def test_registers_the_five_filters(self):
        self.assertEqual(
            set(FilterModule().filters()),
            {
                "swarm_ingress_sections",
                "swarm_ingress_published",
                "swarm_public_ports",
                "swarm_ingress_guarded",
                "swarm_node_addresses",
            },
        )


if __name__ == "__main__":
    unittest.main()
