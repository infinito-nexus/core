import unittest

from utils.networks.ownership import ownership_errors

DECLARED = {
    "matomo": [("web-app-matomo", "192.168.31.0/24")],
    "postgres": [("svc-db-postgres", "192.168.200.0/24")],
}
SHARED = {
    "litellm": [
        ("web-app-litellm", "192.168.76.0/24"),
        ("svc-ai-litellm", "192.168.80.0/24"),
    ],
}


def _network(name, *subnets, project=None):
    labels = {} if project is None else {"com.docker.compose.project": project}
    return {
        "Name": name,
        "Labels": labels,
        "IPAM": {"Config": [{"Subnet": subnet} for subnet in subnets]},
    }


class TestOwnershipErrors(unittest.TestCase):
    def test_networks_that_match_their_owner_pass(self):
        networks = [
            _network("matomo", "192.168.31.0/24", project="matomo"),
            _network("postgres", "192.168.200.0/24", project="postgres"),
        ]
        self.assertEqual(ownership_errors(networks, DECLARED), [])

    def test_a_network_inside_its_widened_block_passes(self):
        networks = [_network("matomo", "192.168.31.0/28", project="matomo")]
        self.assertEqual(ownership_errors(networks, DECLARED), [])

    def test_a_network_reaching_beyond_its_block_is_drift(self):
        networks = [_network("matomo", "192.168.30.0/23", project="matomo")]
        self.assertEqual(
            ownership_errors(networks, DECLARED),
            [
                "network 'matomo' holds 192.168.30.0/23, but web-app-matomo declares 192.168.31.0/24"
            ],
        )

    def test_roles_sharing_an_entity_each_pass_with_their_subnet(self):
        networks = [_network("litellm", "192.168.80.0/24", project="litellm")]
        self.assertEqual(ownership_errors(networks, SHARED), [])

    def test_roles_sharing_an_entity_name_every_accepted_subnet_on_drift(self):
        networks = [_network("litellm", "192.168.90.0/24", project="litellm")]
        self.assertEqual(
            ownership_errors(networks, SHARED),
            [
                (
                    "network 'litellm' holds 192.168.90.0/24, but svc-ai-litellm "
                    "declares 192.168.80.0/24 or web-app-litellm declares 192.168.76.0/24"
                )
            ],
        )

    def test_system_and_auto_addressed_networks_pass(self):
        networks = [
            _network("bridge", "172.17.0.0/16"),
            {"Name": "host", "Labels": {}, "IPAM": {"Config": []}},
            {"Name": "none", "Labels": None, "IPAM": {"Config": None}},
            _network("matomo_default", "10.208.3.0/24", project="matomo"),
        ]
        self.assertEqual(ownership_errors(networks, DECLARED), [])

    def test_an_ipv6_subnet_next_to_the_declared_one_passes(self):
        networks = [
            _network("matomo", "192.168.31.0/24", "fd00:31::/64", project="matomo")
        ]
        self.assertEqual(ownership_errors(networks, DECLARED), [])

    def test_a_drifted_subnet_names_the_owner_and_both_subnets(self):
        networks = [_network("matomo", "192.168.40.0/24", project="matomo")]
        self.assertEqual(
            ownership_errors(networks, DECLARED),
            [
                "network 'matomo' holds 192.168.40.0/24, but web-app-matomo declares 192.168.31.0/24"
            ],
        )

    def test_a_network_without_a_subnet_is_drift(self):
        networks = [
            {"Name": "matomo", "Labels": {"com.docker.compose.project": "matomo"}}
        ]
        self.assertEqual(
            ownership_errors(networks, DECLARED),
            [
                "network 'matomo' holds no subnet, but web-app-matomo declares 192.168.31.0/24"
            ],
        )

    def test_a_foreign_compose_project_is_reported(self):
        networks = [_network("matomo", "192.168.31.0/24", project="nextcloud")]
        self.assertEqual(
            ownership_errors(networks, DECLARED),
            [
                (
                    "network 'matomo' belongs to compose project 'nextcloud', "
                    "but it is the network of web-app-matomo"
                )
            ],
        )

    def test_an_unlabeled_network_on_its_subnet_passes(self):
        networks = [
            _network("matomo", "192.168.31.0/24"),
            _network("postgres", "192.168.200.0/24"),
        ]
        self.assertEqual(ownership_errors(networks, DECLARED), [])

    def test_a_network_labelled_with_its_role_id_passes(self):
        networks = [_network("postgres", "192.168.200.0/24", project="svc-db-postgres")]
        self.assertEqual(ownership_errors(networks, DECLARED), [])

    def test_an_unlabeled_network_off_its_subnet_is_still_drift(self):
        networks = [_network("matomo", "192.168.40.0/24")]
        self.assertEqual(
            ownership_errors(networks, DECLARED),
            [
                "network 'matomo' holds 192.168.40.0/24, but web-app-matomo declares 192.168.31.0/24"
            ],
        )

    def test_a_foreign_network_on_a_declared_subnet_is_reported(self):
        networks = [_network("legacy", "192.168.200.0/25")]
        self.assertEqual(
            ownership_errors(networks, DECLARED),
            [
                (
                    "network 'legacy' occupies 192.168.200.0/25, which svc-db-postgres "
                    "declares for its network 'postgres'"
                )
            ],
        )

    def test_a_secondary_network_of_the_owning_project_on_its_subnet_passes(self):
        declared = {"bigbluebutton": [("web-app-bigbluebutton", "10.7.7.0/24")]}
        networks = [
            _network("bigbluebutton_bbb-net", "10.7.7.0/24", project="bigbluebutton")
        ]
        self.assertEqual(ownership_errors(networks, declared), [])

    def test_a_foreign_project_on_a_declared_subnet_is_still_reported(self):
        networks = [_network("legacy_net", "192.168.200.0/25", project="legacy")]
        self.assertEqual(len(ownership_errors(networks, DECLARED)), 1)

    def test_an_owner_on_another_owners_subnet_reports_drift_and_clash(self):
        networks = [_network("matomo", "192.168.200.0/24", project="matomo")]
        self.assertEqual(
            ownership_errors(networks, DECLARED),
            [
                "network 'matomo' holds 192.168.200.0/24, but web-app-matomo declares 192.168.31.0/24",
                (
                    "network 'matomo' occupies 192.168.200.0/24, which svc-db-postgres "
                    "declares for its network 'postgres'"
                ),
            ],
        )

    def test_an_ipv6_subnet_never_clashes_with_an_ipv4_declaration(self):
        networks = [_network("v6only", "::c0a8:1f00/120")]
        self.assertEqual(ownership_errors(networks, DECLARED), [])


if __name__ == "__main__":
    unittest.main()
