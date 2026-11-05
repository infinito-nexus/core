"""Enforce the 041 instance model in every HA-capable engine role.

Every HA-capable engine's compose template renders one service per
instance from ``lookup('db_instances')`` and mounts the per-instance volume
through ``container_volumes(..., instance=db_instance)``. A template that
skips the loop would render one service that Swarm places on any manager with
an empty volume, and a template that skips ``instance=`` would mount one
volume name on every node.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.roles.db.backup import BACKUP_SQL
from utils.roles.db.instances import (
    PRIMARY_PROBE_HTTP,
    build_instances,
    engine_word,
    ha_engines,
    ha_spec,
)
from utils.roles.entity.name import get_entity_name
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

from . import PROJECT_ROOT

_LOOP = "lookup('db_instances')"
_MOUNT = "instance=db_instance"


class TestDbInstanceModel(unittest.TestCase):
    def test_engine_templates_loop_over_instances(self):
        templates = [
            PROJECT_ROOT / "roles" / role / ROLE_FILE_TEMPL_COMPOSE
            for role in sorted(ha_engines())
        ]
        offenders = [
            str(path.relative_to(PROJECT_ROOT))
            for path in templates
            if _LOOP not in (text := read_text(str(path))) or _MOUNT not in text
        ]
        self.assertEqual(
            offenders,
            [],
            f"engine compose templates must use {_LOOP} and pass {_MOUNT} "
            "to container_volumes",
        )


class TestDbInstanceBackup(unittest.TestCase):
    """baudolo finds a database container by the engine word after ``_`` or
    ``-`` in its name and maps it to a ``databases.csv`` instance, so an HA
    instance that lost the word would silently go undumped."""

    def test_ha_instance_names_keep_engine_word(self):
        nodes = ["mgr-01", "mgr-02", "mgr-03"]
        offenders = []
        for app_id in sorted(
            r for r in ha_engines() if ha_spec(r)["backup"] == BACKUP_SQL
        ):
            engine = engine_word(app_id)
            model = build_instances(
                app_id, nodes, deployment_mode="swarm", swarm_nodes=nodes
            )
            for instance in model["instances"]:
                task = f"{engine}_{instance['service']}.1.abc"
                match = re.search(rf"(_|-)({engine})", task)
                if not match or task[: match.start()] != engine:
                    offenders.append(instance["service"])
        self.assertEqual(offenders, [], "HA instance names must keep the engine word")

    def test_backup_unit_runs_through_the_ha_gate(self):
        text = read_text(
            str(PROJECT_ROOT / "roles" / "svc-bkp-volume-2-local" / ROLE_FILE_VARS_MAIN)
        )
        exec_block = text.split("BKP_VOLUME_2_LOCAL_EXEC:", 1)[1]
        self.assertTrue(
            exec_block.lstrip(" >-\n").startswith(
                "{{ (BKP_VOLUME_2_LOCAL_HA_GATE_ARGS + [BKP_VOLUME_2_LOCAL_SNAPSHOT_BIN])"
            ),
            "the backup unit must start baudolo through baudolo-ha-gate on HA hosts, "
            "which keeps replica database volumes out of file-level backups and fails "
            "on a missing dump",
        )
        gate_block = text.split("\nBKP_VOLUME_2_LOCAL_HA_GATE_ARGS:", 1)[1].split(
            "\n\n", 1
        )[0]
        self.assertIn("BKP_VOLUME_2_LOCAL_HA_GATE_BIN", gate_block)
        self.assertIn(
            "BKP_VOLUME_2_LOCAL_HA_LOCAL",
            gate_block,
            "the gate must only wrap the command on a host with local HA instances, "
            "so a standalone host keeps today's command",
        )

    def test_unbacked_engines_disable_backup(self):
        offenders = []
        for role in sorted(r for r in ha_engines() if not ha_spec(r)["backup"]):
            services = load_yaml(
                PROJECT_ROOT / "roles" / role / ROLE_FILE_META_SERVICES
            )
            entity = get_entity_name(role)
            if not (services.get(entity, {}).get("backup") or {}).get("disabled"):
                offenders.append(role)
        self.assertEqual(
            offenders,
            [],
            "an HA engine without ha.backup must disable its backup in meta",
        )

    def test_declared_primary_probes_exist(self):
        missing = [
            spec["primary_probe"]
            for spec in (ha_spec(role) for role in sorted(ha_engines()))
            if spec["primary_probe"]
            and spec["primary_probe"] != PRIMARY_PROBE_HTTP
            and not (PROJECT_ROOT / spec["primary_probe"]).is_file()
        ]
        self.assertEqual(missing, [], "ha.primary_probe must name a script in the repo")

    def test_backed_up_engines_declare_a_primary_probe(self):
        offenders = [
            role
            for role in sorted(ha_engines())
            if ha_spec(role)["backup"] and not ha_spec(role)["probe"]
        ]
        self.assertEqual(
            offenders,
            [],
            "the backup gate needs ha.primary_probe for every ha.backup engine",
        )


if __name__ == "__main__":
    unittest.main()
