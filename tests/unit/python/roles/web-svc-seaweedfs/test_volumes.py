import unittest

from plugins.lookup.container_volumes import container_volumes
from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.mapping import (
    ROLE_FILE_META_VOLUMES,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

ROLE = "web-svc-seaweedfs"
ROLE_DIR = PROJECT_ROOT / "roles" / ROLE
CONFIG_DIR = "/opt/compositions/web-svc-seaweedfs/volumes/s3"
TARGET = "/etc/seaweedfs/s3"


def _render_source(expression):
    if "{{" not in expression:
        return expression
    if "'s3' ]" not in expression:
        raise AssertionError(f"unexpected bind source {expression!r}")
    return CONFIG_DIR


class TestSeaweedfsVolumes(unittest.TestCase):
    def setUp(self):
        self.entry = load_yaml_any(str(ROLE_DIR / ROLE_FILE_META_VOLUMES))["s3_config"]
        self.vars = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))

    def test_the_s3_config_is_mounted_as_a_directory(self):
        self.assertEqual(self.entry["type"], "bind")
        self.assertTrue(self.entry["read_only"])
        self.assertEqual([mount["target"] for mount in self.entry["mounts"]], [TARGET])
        block = load_yaml_str(
            container_volumes({}, ROLE, "seaweedfs", render_jinja=_render_source)
        )
        self.assertIn(f"{CONFIG_DIR}:{TARGET}:ro", block["volumes"])
        self.assertNotIn("configs", block)

    def test_the_host_file_lies_in_the_mounted_directory(self):
        source = self.entry["source"].replace("'web-svc-seaweedfs'", "application_id")
        self.assertEqual(source, self.vars["SEAWEEDFS_S3_CONFIG_DIR"])
        self.assertEqual(
            self.vars["SEAWEEDFS_S3_CONFIG_PATH"],
            "{{ [ SEAWEEDFS_S3_CONFIG_DIR, 's3.json' ] | path_join }}",
        )

    def test_the_server_reads_the_file_inside_the_mount(self):
        self.assertEqual(
            self.vars["SEAWEEDFS_S3_CONFIG_TARGET"],
            "{{ [ lookup('volume', application_id, 's3_config').target, 's3.json' ] | path_join }}",
        )
        compose = read_text(str(ROLE_DIR / ROLE_FILE_TEMPL_COMPOSE))
        self.assertIn("SEAWEEDFS_S3_CONFIG_TARGET | seaweedfs_command(", compose)

    def test_the_identity_records_stay_outside_the_mount(self):
        records = self.vars["SEAWEEDFS_IDENTITIES_DIR"]
        self.assertIn("'identities.d'", records)
        self.assertNotIn("SEAWEEDFS_S3_CONFIG_DIR", records)


if __name__ == "__main__":
    unittest.main()
