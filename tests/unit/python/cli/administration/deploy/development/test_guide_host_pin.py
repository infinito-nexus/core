import unittest
from unittest.mock import patch

from cli.administration.deploy.development.variant_select import env_guide_host_pin

HOST = "web-app-docs"
ROLES = "/repo/roles"

FAT = {"services": {"dashboard": {"enabled": True}, "matomo": {"enabled": True}}}
LEAN = {"services": {"dashboard": {"enabled": False}, "matomo": {"enabled": False}}}


def _variants(mapping):
    return patch(
        "cli.administration.deploy.development.variant_select.get_variants",
        return_value=mapping,
    )


class TestGuideHostPin(unittest.TestCase):
    def test_the_host_takes_the_variant_enabling_fewest_services(self) -> None:
        with (
            patch.dict("os.environ", {"guide_host": HOST}),
            _variants({HOST: [FAT, LEAN]}),
        ):
            self.assertEqual(
                env_guide_host_pin(ROLES, [HOST, "svc-ai-searxng"]), {HOST: 1}
            )

    def test_without_the_variable_nothing_is_pinned(self) -> None:
        with (
            patch.dict("os.environ", {"guide_host": ""}),
            _variants({HOST: [FAT, LEAN]}),
        ):
            self.assertEqual(env_guide_host_pin(ROLES, [HOST]), {})

    def test_a_host_the_round_does_not_deploy_is_not_pinned(self) -> None:
        """Pinning an absent app would add it to the plan through the back door."""
        with (
            patch.dict("os.environ", {"guide_host": HOST}),
            _variants({HOST: [FAT, LEAN]}),
        ):
            self.assertEqual(env_guide_host_pin(ROLES, ["svc-ai-searxng"]), {})

    def test_the_hosts_own_sweep_keeps_its_matrix(self) -> None:
        """The docs row carries the replay too, so the host is also the subject
        there and the round index is the whole point of that sweep."""
        with (
            patch.dict("os.environ", {"guide_host": HOST}),
            _variants({HOST: [FAT, LEAN]}),
        ):
            self.assertEqual(env_guide_host_pin(ROLES, [HOST, HOST]), {})

    def test_a_host_without_variants_is_not_pinned(self) -> None:
        with patch.dict("os.environ", {"guide_host": HOST}), _variants({}):
            self.assertEqual(env_guide_host_pin(ROLES, [HOST]), {})


if __name__ == "__main__":
    unittest.main()
