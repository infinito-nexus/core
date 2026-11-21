from __future__ import annotations

import copy
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VOLUMES,
    ROLE_FILE_VARS_MAIN,
)

ROLE_DIR = PROJECT_ROOT / "roles" / "svc-dns-knot"
SERVICES = load_yaml_str(read_text(str(ROLE_DIR / ROLE_FILE_META_SERVICES)))
VOLUMES = load_yaml_str(read_text(str(ROLE_DIR / ROLE_FILE_META_VOLUMES)))
VARS = load_yaml_str(read_text(str(ROLE_DIR / ROLE_FILE_VARS_MAIN)))
BACKUP_HOST = "{{ 'svc-bkp-volume-2-local' in group_names }}"


def backup_findings(services, volumes):
    """
    Args:
        services: the parsed meta/services.yml of the role.
        volumes: the parsed meta/volumes.yml of the role.

    Returns:
        One finding per gap that leaves the signing keys out of the backup.
    """
    findings = []
    consumer = services.get("container_backup") or {}
    if consumer.get("enabled") != BACKUP_HOST:
        findings.append(f"container_backup enabled is {consumer.get('enabled')!r}")
    if consumer.get("shared") is not True:
        findings.append(f"container_backup shared is {consumer.get('shared')!r}")
    if (services["knot"].get("backup") or {}).get("stop_required") is not True:
        findings.append("knot keeps writing its key database during the backup")
    storage = [
        volume
        for volume in volumes.values()
        if any(mount["target"] == "/storage" for mount in volume["mounts"])
    ]
    if [volume["type"] for volume in storage] != ["volume"]:
        findings.append(f"/storage is not one named volume: {storage}")
    return findings


class TestKnotBackup(unittest.TestCase):
    def test_the_storage_holding_the_signing_keys_is_backed_up(self):
        self.assertEqual(backup_findings(SERVICES, VOLUMES), [])

    def test_the_server_keeps_its_key_database_under_the_backed_up_storage(self):
        self.assertEqual(
            VARS["KNOT_STORAGE_TARGET"],
            "{{ lookup('volume', application_id, 'data').target }}",
        )
        self.assertEqual(VOLUMES["data"]["mounts"][0]["target"], "/storage")

    def test_negative_control_a_role_without_the_backup_consumer_is_reported(self):
        services = copy.deepcopy(SERVICES)
        del services["container_backup"]
        services["knot"].pop("backup")
        volumes = copy.deepcopy(VOLUMES)
        volumes["data"]["type"] = "tmpfs"
        self.assertEqual(
            backup_findings(services, volumes),
            [
                "container_backup enabled is None",
                "container_backup shared is None",
                "knot keeps writing its key database during the backup",
                f"/storage is not one named volume: {[volumes['data']]}",
            ],
        )


if __name__ == "__main__":
    unittest.main()
