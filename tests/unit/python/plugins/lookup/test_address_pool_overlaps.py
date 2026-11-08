import json
import unittest
from unittest import mock

from ansible.errors import AnsibleError

from plugins.lookup.address_pool_overlaps import LookupModule
from utils.preflight.context import DeployClosureContext

MODULE = "plugins.lookup.address_pool_overlaps"
SUBNETS = {"web-app-matomo": "192.168.31.0/24"}
RESERVED = {"NETWORK_MESH_POOL": "10.100.0.0/16"}


def _context():
    return DeployClosureContext(
        roles=["sys-ctl-hlth-csp", "web-app-matomo"],
        applications={},
        config=lambda role, path, default: SUBNETS.get(role, default),
        lookup=mock.Mock(),
    )


class TestAddressPoolOverlapsLookup(unittest.TestCase):
    def _run(self, terms, side_effect=None):
        with (
            mock.patch(
                f"{MODULE}.deploy_closure_context",
                return_value=_context(),
                side_effect=side_effect,
            ),
            mock.patch(
                f"{MODULE}.entity_name", side_effect=lambda role: role.split("-", 2)[-1]
            ),
        ):
            return LookupModule().run(terms, variables={})

    @staticmethod
    def _daemon(*bases):
        return json.dumps(
            {"default-address-pools": [{"base": base, "size": 24} for base in bases]}
        )

    def test_role_subnets_and_reserved_ranges_are_compared(self):
        result = self._run(
            [self._daemon("192.168.0.0/16", "10.0.0.0/8"), ["web-app-matomo"], RESERVED]
        )
        self.assertEqual(
            result,
            [
                [
                    (
                        "docker default address pool 192.168.0.0/16 overlaps "
                        "192.168.31.0/24, which web-app-matomo declares for its "
                        "network 'matomo'"
                    ),
                    (
                        "docker default address pool 10.0.0.0/8 overlaps 10.100.0.0/16, "
                        "which NETWORK_MESH_POOL reserves"
                    ),
                ]
            ],
        )

    def test_a_clear_pool_and_an_absent_file_pass(self):
        self.assertEqual(
            self._run([self._daemon("10.208.0.0/12"), ["web-app-matomo"], RESERVED]),
            [[]],
        )
        self.assertEqual(self._run(["{}", ["web-app-matomo"], RESERVED]), [[]])

    def test_an_unparsable_daemon_json_is_rejected(self):
        with self.assertRaises(AnsibleError):
            self._run(["{not json", [], RESERVED])

    def test_a_pool_without_base_is_rejected(self):
        with self.assertRaises(AnsibleError):
            self._run(['{"default-address-pools": [{"size": 24}]}', [], RESERVED])

    def test_non_mapping_arguments_are_rejected(self):
        with self.assertRaises(AnsibleError):
            self._run(["[]", [], RESERVED])

    def test_a_closure_error_becomes_an_ansible_error(self):
        with self.assertRaises(AnsibleError):
            self._run(["{}", [], RESERVED], side_effect=TypeError("x"))

    def test_a_wrong_term_count_is_rejected(self):
        with self.assertRaises(AnsibleError):
            LookupModule().run(["{}", []])


if __name__ == "__main__":
    unittest.main()
