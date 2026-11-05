import json
import unittest
from unittest import mock

from ansible.errors import AnsibleError

from plugins.lookup.network_ownership import LookupModule

MODULE = "plugins.lookup.network_ownership"
SUBNETS = {"web-app-matomo": "192.168.31.0/24"}


def _config_run(terms, variables=None):
    role, _path, default = terms
    return [SUBNETS.get(role, default)]


class TestNetworkOwnershipLookup(unittest.TestCase):
    def _run(self, terms, closure=None, side_effect=None):
        applications = mock.Mock()
        applications.run.return_value = [{"web-app-matomo": {}}]
        config = mock.Mock()
        config.run.side_effect = _config_run
        with (
            mock.patch(
                f"{MODULE}.lookup_loader.get",
                side_effect=lambda name, **kwargs: {
                    "applications": applications,
                    "config": config,
                }[name],
            ),
            mock.patch(f"{MODULE}.types_from_group_names", return_value=["server"]),
            mock.patch(
                f"{MODULE}.deploy_closure",
                return_value=closure or {"web-app-matomo", "sys-ctl-hlth-csp"},
                side_effect=side_effect,
            ) as closure_mock,
            mock.patch(
                f"{MODULE}.entity_name", side_effect=lambda role: role.split("-", 2)[-1]
            ),
        ):
            result = LookupModule().run(terms, variables={"group_names": terms[-1]})
        return result, closure_mock

    @staticmethod
    def _probe(*networks):
        return {"rc": 0, "stdout": json.dumps(list(networks))}

    def test_roles_with_a_subnet_are_checked_against_the_networks(self):
        probe = self._probe(
            {
                "Name": "matomo",
                "Labels": {"com.docker.compose.project": "matomo"},
                "IPAM": {"Config": [{"Subnet": "192.168.40.0/24"}]},
            }
        )
        result, _closure = self._run([probe, ["web-app-matomo"]])
        self.assertEqual(
            result,
            [
                [
                    "network 'matomo' holds 192.168.40.0/24, but web-app-matomo declares 192.168.31.0/24"
                ]
            ],
        )

    def test_matching_networks_return_no_errors(self):
        probe = self._probe(
            {
                "Name": "matomo",
                "Labels": {"com.docker.compose.project": "matomo"},
                "IPAM": {"Config": [{"Subnet": "192.168.31.0/24"}]},
            }
        )
        result, _closure = self._run([probe, ["web-app-matomo"]])
        self.assertEqual(result, [[]])

    def test_the_host_groups_seed_the_closure(self):
        _result, closure = self._run([self._probe(), ["web-app-matomo", "servers"]])
        self.assertEqual(closure.call_args.args[1], ["web-app-matomo", "servers"])
        self.assertEqual(closure.call_args.kwargs["host_types"], ["server"])

    def test_an_unparsable_probe_is_rejected(self):
        with self.assertRaises(AnsibleError):
            self._run([{"rc": 0, "stdout": "not json"}, ["web-app-matomo"]])

    def test_a_closure_error_becomes_an_ansible_error(self):
        with self.assertRaises(AnsibleError):
            self._run(
                [self._probe(), ["web-app-matomo"]], side_effect=ValueError("broken")
            )

    def test_a_wrong_term_count_is_rejected(self):
        with self.assertRaises(AnsibleError):
            LookupModule().run([self._probe()])


if __name__ == "__main__":
    unittest.main()
