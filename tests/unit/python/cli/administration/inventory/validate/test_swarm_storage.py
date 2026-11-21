import shutil
import tempfile
import unittest
from pathlib import Path

from cli.administration.inventory.validate.swarm_storage import (
    BLOCK_DEFAULTS,
    block_errors,
    validate_swarm_storage,
)
from utils.cache.yaml import dump_yaml_str, load_yaml

from . import PROJECT_ROOT

NFS_STORAGE = {"backend": "nfs", "nfs": {"server": "10.0.0.20"}}
FULL_SWARM = {
    "manager": {"advertise_addr": "10.0.0.10"},
    "network": {"encryption": True},
    "registry": {"host": "swarm-mgr-01", "port": 5000},
}


def _default(name: str) -> dict:
    return load_yaml(str(PROJECT_ROOT / BLOCK_DEFAULTS[name]))[name]


def _storage(value) -> list[str]:
    return block_errors("storage", value, _default("storage"))


def _swarm(value) -> list[str]:
    return block_errors("swarm", value, _default("swarm"))


class TestStorageBlock(unittest.TestCase):
    def test_the_group_vars_default_passes(self):
        self.assertEqual([], _storage(_default("storage")))

    def test_an_nfs_backend_with_its_server_passes(self):
        self.assertEqual([], _storage(NFS_STORAGE))

    def test_a_local_backend_needs_no_nfs_block(self):
        self.assertEqual([], _storage({"backend": "local"}))

    def test_an_unknown_backend_fails(self):
        self.assertEqual(
            ["'storage.backend' must be one of local, nfs, got 'nsf'"],
            _storage({"backend": "nsf"}),
        )

    def test_a_templated_backend_passes(self):
        self.assertEqual([], _storage({"backend": "{{ STORAGE_BACKEND }}"}))

    def test_an_nfs_backend_without_a_server_fails(self):
        errors = _storage({"backend": "nfs"})
        self.assertEqual(1, len(errors))
        self.assertIn("'storage.nfs.server' is missing", errors[0])

    def test_a_missing_backend_fails(self):
        errors = _storage({"nfs": {"server": "10.0.0.20"}})
        self.assertEqual(1, len(errors))
        self.assertIn("'storage.backend' is missing", errors[0])

    def test_a_misspelled_key_fails_as_unknown(self):
        errors = _storage({"backend": "local", "nsf": {}})
        self.assertEqual(1, len(errors))
        self.assertIn("'storage.nsf' is unknown", errors[0])

    def test_a_scalar_instead_of_a_mapping_fails(self):
        self.assertEqual(["'storage' must be a mapping, got str"], _storage("nfs"))

    def test_a_server_of_the_wrong_type_fails(self):
        errors = _storage({"backend": "nfs", "nfs": {"server": 10}})
        self.assertEqual(["'storage.nfs.server' must be str, got int"], errors)


class TestSwarmBlock(unittest.TestCase):
    def test_the_group_vars_default_passes(self):
        self.assertEqual([], _swarm(_default("swarm")))

    def test_a_full_override_passes(self):
        self.assertEqual([], _swarm(FULL_SWARM))

    def test_the_advertise_addr_may_be_left_out(self):
        self.assertEqual(
            [], _swarm({k: v for k, v in FULL_SWARM.items() if k != "manager"})
        )

    def test_an_override_of_the_encryption_alone_fails_for_the_registry(self):
        errors = _swarm({"network": {"encryption": False}})
        self.assertEqual(2, len(errors))
        self.assertIn("'swarm.registry.host' is missing", errors[0])
        self.assertIn("'swarm.registry.port' is missing", errors[1])

    def test_a_string_encryption_fails(self):
        value = {**FULL_SWARM, "network": {"encryption": "false"}}
        self.assertEqual(
            ["'swarm.network.encryption' must be bool, got str"], _swarm(value)
        )

    def test_a_templated_encryption_passes(self):
        value = {**FULL_SWARM, "network": {"encryption": "{{ ENCRYPT | bool }}"}}
        self.assertEqual([], _swarm(value))

    def test_a_boolean_port_fails(self):
        value = {**FULL_SWARM, "registry": {"host": "mgr", "port": True}}
        self.assertEqual(["'swarm.registry.port' must be int, got bool"], _swarm(value))

    def test_a_worker_list_is_rejected_as_unknown(self):
        errors = _swarm({**FULL_SWARM, "worker_nodes": ["swarm-wrk-01"]})
        self.assertEqual(1, len(errors))
        self.assertIn("'swarm.worker_nodes' is unknown", errors[0])


class TestValidateSwarmStorage(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        (self.root / "host_vars").mkdir()
        (self.root / "group_vars").mkdir()

    def _write(self, relative: str, data: dict) -> Path:
        path = self.root / relative
        path.write_text(dump_yaml_str(data), encoding="utf-8")
        return path

    def test_a_well_formed_inventory_passes(self):
        self._write("host_vars/echo.yml", {"storage": NFS_STORAGE, "swarm": FULL_SWARM})
        self.assertEqual([], validate_swarm_storage(self.root))

    def test_a_host_vars_problem_names_its_file(self):
        path = self._write("host_vars/echo.yml", {"storage": {"backend": "nsf"}})
        errors = validate_swarm_storage(self.root)
        self.assertEqual(1, len(errors))
        self.assertTrue(errors[0].startswith(f"{path}: 'storage.backend'"))

    def test_a_group_vars_problem_is_reported(self):
        self._write("group_vars/all.yml", {"swarm": {"network": {"encryption": True}}})
        self.assertEqual(2, len(validate_swarm_storage(self.root)))

    def test_an_inventory_without_either_block_passes(self):
        self._write("host_vars/echo.yml", {"DOMAIN_PRIMARY": "example.org"})
        self.assertEqual([], validate_swarm_storage(self.root))


if __name__ == "__main__":
    unittest.main()
