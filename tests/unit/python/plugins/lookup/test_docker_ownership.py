import unittest
from unittest import mock

from ansible.errors import AnsibleError

from plugins.lookup.docker_ownership import LookupModule
from utils.preflight.context import DeployClosureContext

MODULE = "plugins.lookup.docker_ownership"
APPLICATIONS = {
    "web-app-matomo": {
        "services": {
            "matomo": {"name": "matomo", "image": "matomo"},
            "mariadb": {"enabled": True, "shared": True},
        }
    },
    "svc-db-mariadb": {"services": {"mariadb": {"name": "mariadb"}}},
    "web-app-discourse": {"services": {"discourse": {"name": "discourse"}}},
}
LAUNCHERS = {"web-app-discourse"}
VOLUMES = {
    "web-app-matomo": {
        "data": {"type": "volume", "name": "matomo_data"},
        "cache": {},
        "php_hardening": {"type": "config", "source": "/etc/php.ini"},
    },
}


def _config(role, path, default):
    if path == "networks.local.launcher":
        return role in LAUNCHERS
    return APPLICATIONS[role]["services"][path.split(".")[1]]["name"]


def _context(roles=("svc-db-mariadb", "web-app-matomo", "web-app-discourse")):
    return DeployClosureContext(
        roles=list(roles),
        applications=APPLICATIONS,
        config=_config,
        lookup=lambda name, role: VOLUMES.get(role, {}),
    )


class TestDockerOwnershipLookup(unittest.TestCase):
    def _run(self, terms, side_effect=None):
        with (
            mock.patch(
                f"{MODULE}.deploy_closure_context",
                return_value=_context(),
                side_effect=side_effect,
            ) as context,
            mock.patch(
                f"{MODULE}.entity_name", side_effect=lambda role: role.split("-", 2)[-1]
            ),
        ):
            result = LookupModule().run(terms, variables={})
        return result, context

    def test_containers_declared_by_name_are_checked(self):
        probe = {"stdout": "matomo\tnextcloud\t\nmariadb\tmariadb\t\nlegacy\t\t"}
        result, _context_mock = self._run(["container", probe, ["web-app-matomo"]])
        self.assertEqual(
            result,
            [
                [
                    (
                        "container 'matomo' belongs to compose project 'nextcloud', "
                        "but it is the container of web-app-matomo (entity 'matomo')"
                    )
                ]
            ],
        )

    def test_a_launcher_role_container_needs_no_compose_label(self):
        probe = {"stdout": "discourse\t\t\nmatomo\tmatomo\t"}
        result, _context_mock = self._run(["container", probe, ["web-app-discourse"]])
        self.assertEqual(result, [[]])

    def test_volumes_use_their_name_or_the_compose_default(self):
        probe = {
            "stdout": (
                "matomo_data\tnextcloud\t\n"
                "matomo_cache\tnextcloud\t\n"
                "matomo_php_hardening\tnextcloud\t"
            )
        }
        result, _context_mock = self._run(["volume", probe, ["web-app-matomo"]])
        self.assertEqual(
            result,
            [
                [
                    (
                        "volume 'matomo_data' belongs to compose project 'nextcloud', "
                        "but it is the volume of web-app-matomo (entity 'matomo')"
                    ),
                    (
                        "volume 'matomo_cache' belongs to compose project 'nextcloud', "
                        "but it is the volume of web-app-matomo (entity 'matomo')"
                    ),
                ]
            ],
        )

    def test_the_host_groups_reach_the_closure(self):
        _result, context = self._run(["volume", {"stdout": ""}, ["web-app-matomo"]])
        self.assertEqual(context.call_args.args[2], ["web-app-matomo"])

    def test_an_unknown_kind_is_rejected(self):
        with self.assertRaises(AnsibleError):
            self._run(["network", {"stdout": ""}, []])

    def test_an_unparsable_probe_is_rejected(self):
        with self.assertRaises(AnsibleError):
            self._run(["container", {"stdout": "only-a-name"}, []])

    def test_a_closure_error_becomes_an_ansible_error(self):
        with self.assertRaises(AnsibleError):
            self._run(["container", {"stdout": ""}, []], side_effect=ValueError("x"))

    def test_a_wrong_term_count_is_rejected(self):
        with self.assertRaises(AnsibleError):
            LookupModule().run(["container", {"stdout": ""}])


if __name__ == "__main__":
    unittest.main()
