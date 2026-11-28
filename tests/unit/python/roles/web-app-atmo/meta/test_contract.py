import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import (
    ROLE_FILE_META_CSP,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VOLUMES,
    ROLE_FILE_VARS_MAIN,
)

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-atmo"


def _yaml(relative: str):
    return load_yaml_str(read_text(str(ROLE / relative)))


def _render(expression: str, **variables) -> str:
    """
    Args:
        expression: a Jinja string from the role's YAML.
        variables: the variables it renders with.

    Returns:
        The rendered string.
    """
    environment = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    environment.filters["bool"] = bool
    return environment.from_string(expression).render(**variables)


class TestServicesContract(unittest.TestCase):
    def setUp(self):
        self.services = _yaml(ROLE_FILE_META_SERVICES)
        self.vars = _yaml(ROLE_FILE_VARS_MAIN)

    def test_atmo_image_is_self_built_from_a_pinned_commit(self):
        atmo = self.services["atmo"]
        self.assertIs(atmo["custom"], True)
        self.assertRegex(atmo["ref"], r"^[0-9a-f]{40}$")
        self.assertEqual(
            atmo["repository"], "https://github.com/flo-bit/atmo-events.git"
        )
        self.assertNotIn("latest", str(atmo["version"]))
        self.assertTrue((ROLE / "files" / "Dockerfile").is_file())

    def test_bridge_is_gated_on_both_partner_roles(self):
        enabled = self.services["bridge"]["enabled"]
        for partners, expected in (
            ((), "False"),
            (("web-app-mobilizon",), "False"),
            (("web-app-bluesky",), "False"),
            (("web-app-mobilizon", "web-app-bluesky"), "True"),
        ):
            with self.subTest(partners=partners):
                self.assertEqual(
                    _render(enabled, group_names=["web-app-atmo", *partners]),
                    expected,
                )
        for value in (True, False):
            with self.subTest(configured=value):
                self.assertEqual(
                    _render(
                        self.vars["ATMO_BRIDGE_ENABLED"],
                        application_id="web-app-atmo",
                        lookup=lambda *terms, value=value: {
                            ("config", "web-app-atmo", "services.bridge.enabled"): value
                        }[terms],
                    ),
                    str(value),
                )

    def test_stateful_services_run_single_replica_on_one_node(self):
        self.assertEqual(self.services["atmo"]["placement"], "manager")
        for name in ("atmo", "cron", "bridge"):
            with self.subTest(service=name):
                self.assertEqual(self.services[name]["replicas"], 1)


class TestVolumesContract(unittest.TestCase):
    def setUp(self):
        self.volumes = _yaml(ROLE_FILE_META_VOLUMES)
        self.vars = _yaml(ROLE_FILE_VARS_MAIN)

    def test_aggregator_cache_lives_in_a_role_local_volume(self):
        data = self.volumes["data"]
        self.assertEqual(data["type"], "volume")
        self.assertIs(data["nfs"], False)
        self.assertEqual(
            data["mounts"], [{"service": "atmo", "target": self.vars["ATMO_DATA_DIR"]}]
        )

    def test_bridge_mapping_lives_in_a_role_local_volume(self):
        state = self.volumes["bridge_state"]
        self.assertEqual(state["type"], "volume")
        self.assertIs(state["nfs"], False)
        self.assertEqual([mount["service"] for mount in state["mounts"]], ["bridge"])
        self.assertEqual(
            self.vars["ATMO_BRIDGE_STATE_DIR"],
            "{{ lookup('volume', application_id, 'bridge_state').target }}",
        )
        env = read_text(str(ROLE / "templates" / "env" / "bridge.j2"))
        self.assertIn(
            "BRIDGE_STATE_PATH={{ [ATMO_BRIDGE_STATE_DIR, 'state.sqlite'] | path_join",
            env,
        )


class TestCspContract(unittest.TestCase):
    def test_connect_src_covers_the_pds_and_the_firehose(self):
        connect = _yaml(ROLE_FILE_META_CSP)["whitelist"]["connect-src"]
        self.assertIn(
            "{{ lookup('canonical_url', 'web-app-bluesky', 'api') }}", connect
        )
        sockets = [entry for entry in connect if entry.startswith("wss://")]
        self.assertEqual(sockets, ["wss://jetstream2.us-east.bsky.network"])


if __name__ == "__main__":
    unittest.main()
