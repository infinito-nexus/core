import importlib.util
import unittest
from types import ModuleType
from unittest import mock

from . import PROJECT_ROOT


def _load_module() -> ModuleType:
    plugin_path = (
        PROJECT_ROOT
        / "roles"
        / "svc-bkp-volume-2-local"
        / "lookup_plugins"
        / "backup_volume.py"
    )
    spec = importlib.util.spec_from_file_location("backup_volume", plugin_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _run(module: ModuleType, applications: dict) -> list[str]:
    loader = mock.MagicMock()
    loader.get.return_value.run.return_value = [applications]
    with mock.patch.object(module, "lookup_loader", loader):
        plugin = module.LookupModule()
        return plugin.run(None, variables={})[0]


class TestBackupVolumeLookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._module = _load_module()

    def test_only_backup_false_is_emitted(self) -> None:
        apps = {
            "web-app-matrix": {
                "volumes": {
                    "mdad_docker": {"name": "matrix_mdad_docker", "backup": False},
                    "mdad_matrix": {"name": "matrix_mdad_matrix"},
                    "mdad_state": {"name": "matrix_mdad_state", "backup": True},
                }
            }
        }
        self.assertEqual(_run(type(self)._module, apps), ["matrix_mdad_docker"])

    def test_the_pinned_docker_name_wins_over_the_semantic_key(self) -> None:
        apps = {"r": {"volumes": {"semantic": {"name": "pinned", "backup": False}}}}
        self.assertEqual(_run(type(self)._module, apps), ["pinned"])

    def test_a_nameless_entry_falls_back_to_its_key(self) -> None:
        apps = {"r": {"volumes": {"semantic": {"backup": False}}}}
        self.assertEqual(_run(type(self)._module, apps), ["semantic"])

    def test_names_are_deduplicated_and_sorted(self) -> None:
        apps = {
            "a": {"volumes": {"v": {"name": "zeta", "backup": False}}},
            "b": {"volumes": {"v": {"name": "zeta", "backup": False}}},
            "c": {"volumes": {"v": {"name": "alpha", "backup": False}}},
        }
        self.assertEqual(_run(type(self)._module, apps), ["alpha", "zeta"])

    def test_an_app_without_volumes_is_skipped(self) -> None:
        apps = {"a": {"services": {}}, "b": {"volumes": None}}
        self.assertEqual(_run(type(self)._module, apps), [])

    def test_a_truthy_string_is_not_treated_as_an_opt_out(self) -> None:
        apps = {"r": {"volumes": {"v": {"name": "kept", "backup": "false"}}}}
        self.assertEqual(_run(type(self)._module, apps), [])


if __name__ == "__main__":
    unittest.main()
