import tempfile
import unittest
from pathlib import Path

from cli.administration.inventory.provision.yaml_io import dump_yaml, load_yaml
from utils.cache.yaml import dump_yaml_str

_VAULT_CRED = """\
applications:
  svc-db-mariadb:
    credentials:
      root_password: !vault |
        $ANSIBLE_VAULT;1.1;AES256
        33323532656330393531653863306437306438353765363637326435636235396237
        3435626336306666643833633030333736316234623365610a303233663130636566
"""


class TestYamlIO(unittest.TestCase):
    def test_load_yaml_missing_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "missing.yml"
            self.assertEqual(load_yaml(p), {})

    def test_dump_then_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "a.yml"
            data = {"a": 1, "b": {"c": True}}
            dump_yaml(p, data)
            self.assertEqual(load_yaml(p), data)

    def test_a_round_trip_keeps_the_vault_tag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "host_vars.yml"
            p.write_text(_VAULT_CRED, encoding="utf-8")
            data = load_yaml(p)
            data["NETWORK_MODE"] = "multi"
            dump_yaml(p, data)
            out = p.read_text(encoding="utf-8")  # nocheck: cache-read -- tempdir
            self.assertIn("!vault |", out)
            self.assertNotIn("root_password: '$ANSIBLE_VAULT", out)

    def test_load_yaml_rejects_non_mapping(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "bad.yml"
            p.write_text(dump_yaml_str(["not-a-mapping"]), encoding="utf-8")
            with self.assertRaises(SystemExit):
                load_yaml(p)
