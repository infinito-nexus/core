from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.env.parser import parse_static_env
from utils.tests.swarm.write import extras as write_extras


class TestWriteExtrasDomainPrimary(unittest.TestCase):
    def _run(self, td: str, extra_env: dict[str, str]) -> dict:
        out_path = Path(td) / "extras.yml"
        env = {
            "NFS_IP": "192.168.244.2",
            "MGR_IP": "192.168.244.3",
            "MGR": "swarm-mgr-01",
            "OUT_PATH": str(out_path),
            "KEY_PATH": str(Path(td) / "admin.key"),
            "INFINITO_SWARM_BACKUP_KEY": str(Path(td) / "backup.key"),
            **extra_env,
        }
        with mock.patch.dict("os.environ", env, clear=False):
            self.assertEqual(write_extras.main(), 0)
        return load_yaml_any(str(out_path))

    def test_domain_primary_defaults_to_static_env(self):
        """The nfs-server host has no host_vars, so the extras file is its
        only source for the cluster domain; without it the host renders
        unresolvable *.infinito.localhost endpoints (msmtp NOHOST)."""
        with tempfile.TemporaryDirectory() as td:
            extras = self._run(td, {"INFINITO_DOMAIN": ""})
        expected = parse_static_env(PROJECT_ROOT / "default.env")["INFINITO_DOMAIN"]
        self.assertEqual(extras["DOMAIN_PRIMARY"], expected)

    def test_domain_primary_honours_env_override(self):
        with tempfile.TemporaryDirectory() as td:
            extras = self._run(td, {"INFINITO_DOMAIN": "override.example"})
        self.assertEqual(extras["DOMAIN_PRIMARY"], "override.example")
