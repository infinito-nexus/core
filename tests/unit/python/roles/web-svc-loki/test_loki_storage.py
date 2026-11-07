"""Loki keeps its chunks in the object store when one is deployed, else on a pinned local volume."""

from __future__ import annotations

import importlib.util
import json
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VOLUMES,
    ROLE_FILE_VARS_MAIN,
)

ROLE = PROJECT_ROOT / "roles" / "web-svc-loki"
SERVICES = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES))
VOLUMES = load_yaml_any(str(ROLE / ROLE_FILE_META_VOLUMES))
VARS = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
OBJSTORE = {
    "endpoint": "seaweedfs:8333",
    "bucket": "web-svc-loki",
    "region": "us-east-1",
}

_SPEC = importlib.util.spec_from_file_location(
    "loki_retention", ROLE / "filter_plugins" / "loki_retention.py"
)
_RETENTION = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_RETENTION)


def _bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "on", "1"}
    return bool(value)


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(ROLE / "templates")),
        trim_blocks=True,
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["to_json"] = json.dumps
    env.filters["bool"] = _bool
    env.globals["lookup"] = lambda name, _app, key: {"objstore": OBJSTORE}[name][key]
    return env


def _render(*, objstore: bool) -> dict:
    env = _environment()
    store = env.from_string(VARS["LOKI_STORE"]).render(LOKI_OBJSTORE_ENABLED=objstore)
    rendered = env.get_template("loki.yaml.j2").render(
        application_id="web-svc-loki",
        LOKI_INTERNAL_PORT=3100,
        LOKI_OBJSTORE_ENABLED=objstore,
        LOKI_STORE=store,
        LOKI_WAL_DISK_FULL_THRESHOLD=0.9,
        LOKI_RETENTION=_RETENTION.loki_retention(
            SERVICES["loki"]["retention"], VARS["LOKI_RETENTION_LABEL"]
        ),
        LOKI_INGESTION_RATE_MB=16,
        LOKI_INGESTION_BURST_MB=64,
        LOKI_ALERTMANAGER_ENABLED=False,
        LOKI_ALERTMANAGER_URL="",
    )
    return load_yaml_str(rendered)


class TestLokiChunkStore(unittest.TestCase):
    def test_with_the_object_store_the_chunks_go_to_s3(self) -> None:
        config = _render(objstore=True)
        s3 = config["common"]["storage"]["s3"]
        self.assertEqual(
            (OBJSTORE["endpoint"], OBJSTORE["bucket"], OBJSTORE["region"]),
            (s3["endpoint"], s3["bucketnames"], s3["region"]),
        )
        self.assertEqual("${LOKI_S3_SECRET_ACCESS_KEY}", s3["secret_access_key"])
        self.assertNotIn("filesystem", config["common"]["storage"])
        self.assertEqual("s3", config["schema_config"]["configs"][0]["object_store"])
        self.assertEqual("s3", config["compactor"]["delete_request_store"])

    def test_without_the_object_store_the_chunks_stay_on_the_data_volume(
        self,
    ) -> None:
        config = _render(objstore=False)
        storage = config["common"]["storage"]
        self.assertNotIn("s3", storage)
        self.assertTrue(storage["filesystem"]["chunks_directory"].startswith("/loki/"))
        self.assertEqual(
            "filesystem", config["schema_config"]["configs"][0]["object_store"]
        )

    def test_the_object_store_follows_the_inventory_groups(self) -> None:
        self.assertEqual(
            "{{ 'web-svc-seaweedfs' in group_names }}",
            SERVICES["seaweedfs"]["enabled"],
        )

    def test_the_data_volume_is_local_pinned_and_not_backed_up(self) -> None:
        data = VOLUMES["data"]
        self.assertEqual("/loki", data["mounts"][0]["target"])
        self.assertIs(False, data["nfs"])
        self.assertIs(False, data["backup"])
        self.assertEqual("manager", SERVICES["loki"]["placement"])
        self.assertEqual(1, SERVICES["loki"]["replicas"])


class TestLokiRetentionConfig(unittest.TestCase):
    def test_every_log_class_keeps_its_own_retention_and_the_compactor_deletes(
        self,
    ) -> None:
        config = _render(objstore=False)
        limits = config["limits_config"]
        self.assertTrue(config["compactor"]["retention_enabled"])
        self.assertEqual("168h", limits["retention_period"])
        self.assertEqual(
            {
                f'{{{VARS["LOKI_RETENTION_LABEL"]}="{name}"}}'
                for name in SERVICES["loki"]["retention"]
            },
            {stream["selector"] for stream in limits["retention_stream"]},
        )


if __name__ == "__main__":
    unittest.main()
