import unittest
from unittest import mock

from ansible.errors import AnsibleError

from plugins.lookup.public_ports import LookupModule
from utils.preflight.context import DeployClosureContext

MODULE = "plugins.lookup.public_ports"
APPLICATIONS = {
    "web-app-mailu": {
        "services": {
            "mailu": {"ports": {"public": {"smtp": 25, "imaps": "993"}}},
            "redis": {"enabled": False},
        }
    },
    "web-svc-coturn": {
        "services": {
            "coturn": {
                "ports": {
                    "public": {
                        "stun_turn": 3478,
                        "relay": {"start": 20000, "end": 39999},
                    },
                    "local": {"http": 8064},
                }
            }
        }
    },
    "web-app-other": {
        "services": {"other": {"ports": {"public": {"smtp": 25, "flag": True}}}}
    },
    "sys-ctl-hlth-csp": {},
}


def _config(role, path, default):
    key = path.split(".")[1]
    return APPLICATIONS[role]["services"][key]["ports"]["public"]


def _context():
    return DeployClosureContext(
        roles=sorted(APPLICATIONS),
        applications=APPLICATIONS,
        config=_config,
        lookup=mock.Mock(),
    )


class TestPublicPortsLookup(unittest.TestCase):
    def _run(self, terms, side_effect=None):
        with mock.patch(
            f"{MODULE}.deploy_closure_context",
            return_value=_context(),
            side_effect=side_effect,
        ):
            return LookupModule().run(terms, variables={})

    def test_single_ports_map_onto_every_role_that_binds_them(self):
        self.assertEqual(
            self._run([["web-app-mailu"]]),
            [
                {
                    "25": ["web-app-mailu (mailu.smtp)", "web-app-other (other.smtp)"],
                    "993": ["web-app-mailu (mailu.imaps)"],
                    "3478": ["web-svc-coturn (coturn.stun_turn)"],
                }
            ],
        )

    def test_a_closure_error_becomes_an_ansible_error(self):
        with self.assertRaises(AnsibleError):
            self._run([[]], side_effect=ValueError("x"))

    def test_a_wrong_term_count_is_rejected(self):
        with self.assertRaises(AnsibleError):
            LookupModule().run([])


if __name__ == "__main__":
    unittest.main()
