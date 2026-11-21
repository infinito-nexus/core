import unittest

from utils.tests.swarm.lab_ports import (
    LAB_REMAPPED_PORT,
    lab_port_overrides,
)


class TestLabPortOverrides(unittest.TestCase):
    def test_knot_moves_its_public_dns_port_off_the_lab_resolver(self) -> None:
        self.assertEqual(
            lab_port_overrides(["svc-dns-knot"]),
            {
                "svc-dns-knot": {
                    "services": {
                        "knot": {"ports": {"public": {"dns": LAB_REMAPPED_PORT}}}
                    }
                }
            },
        )

    def test_a_role_without_a_public_dns_port_stays_untouched(self) -> None:
        self.assertEqual(lab_port_overrides(["svc-dns-unbound"]), {})

    def test_an_unknown_application_is_skipped(self) -> None:
        self.assertEqual(lab_port_overrides(["no-such-role"]), {})


if __name__ == "__main__":
    unittest.main()
