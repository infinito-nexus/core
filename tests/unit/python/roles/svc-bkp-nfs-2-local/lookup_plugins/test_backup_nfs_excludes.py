import importlib.util
import unittest
import unittest.mock as mock
from types import ModuleType
from typing import ClassVar

from . import PROJECT_ROOT

PLUGIN = (
    PROJECT_ROOT
    / "roles"
    / "svc-bkp-nfs-2-local"
    / "lookup_plugins"
    / "backup_nfs_excludes.py"
)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("backup_nfs_excludes", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _run(
    module: ModuleType,
    applications: dict,
    variables: dict,
    templar: object | None = None,
) -> list[str]:
    loader = mock.MagicMock()
    loader.get.return_value.run.return_value = [applications]
    with mock.patch.object(module, "lookup_loader", loader):
        plugin = module.LookupModule()
        if templar is not None:
            plugin._templar = templar
        return plugin.run(None, variables=variables)[0]


class TestBackupNfsExcludes(unittest.TestCase):
    SWARM_NFS: ClassVar[dict] = {
        "DEPLOYMENT_MODE": "swarm",
        "storage": {"backend": "nfs"},
    }

    @classmethod
    def setUpClass(cls) -> None:
        cls._module = _load_module()

    def _excludes(self, applications, variables=None, templar=None):
        return _run(
            type(self)._module,
            applications,
            dict(self.SWARM_NFS) if variables is None else variables,
            templar,
        )

    def test_backup_disabled_volume_dirs_are_excluded(self) -> None:
        apps = {
            "web-app-docs": {
                "volumes": {"docs_sites": {"type": "volume", "backup": False}}
            },
            "web-app-nextcloud": {
                "volumes": {
                    "data": {"type": "volume", "name": "nextcloud_data"},
                    "whiteboard_tmp": {
                        "type": "volume",
                        "name": "nextcloud_whiteboard_tmp",
                        "backup": False,
                    },
                }
            },
        }
        self.assertEqual(
            self._excludes(apps),
            [
                "infinito-state/docs_sites",
                "infinito-state/nextcloud_whiteboard_tmp",
            ],
        )

    def test_the_export_dir_is_the_semantic_key_not_the_docker_name(self) -> None:
        apps = {"web-app-docs": {"volumes": {"docs_sites": {"backup": False}}}}
        self.assertNotIn("infinito-state/docs_docs_sites", self._excludes(apps))

    def test_compose_mode_excludes_nothing(self) -> None:
        apps = {"web-app-docs": {"volumes": {"docs_sites": {"backup": False}}}}
        variables = {"DEPLOYMENT_MODE": "compose", "storage": {"backend": "nfs"}}
        self.assertEqual(self._excludes(apps, variables), [])

    def test_a_volume_off_the_export_is_not_excluded(self) -> None:
        apps = {
            "web-svc-xmpp": {
                "volumes": {
                    "home": {"name": "ejabberd_home", "backup": False, "nfs": False}
                }
            },
            "web-svc-seaweedfs": {
                "volumes": {"data": {"name": "seaweedfs_data", "backup": False}}
            },
        }
        self.assertEqual(self._excludes(apps), [])

    def test_a_dir_a_backed_up_volume_also_binds_stays_captured(self) -> None:
        apps = {
            "web-app-docs": {"volumes": {"shared": {"backup": False}}},
            "web-app-nextcloud": {"volumes": {"shared": {"type": "volume"}}},
        }
        self.assertEqual(self._excludes(apps), [])

    def test_a_config_entry_is_never_excluded(self) -> None:
        apps = {
            "web-app-nextcloud": {
                "volumes": {"loader": {"type": "config", "backup": False}}
            }
        }
        self.assertEqual(self._excludes(apps), [])

    def test_the_deployment_mode_expression_is_templated(self) -> None:
        expression = (
            "{{ 'swarm' if (groups['svc-swarm-node'] | default([]) | length) > 1"
            " else 'compose' }}"
        )
        templar = mock.Mock()
        templar.template.side_effect = lambda value: (
            "swarm" if value == expression else value
        )
        apps = {"web-app-docs": {"volumes": {"docs_sites": {"backup": False}}}}
        self.assertEqual(
            self._excludes(
                apps, {**self.SWARM_NFS, "DEPLOYMENT_MODE": expression}, templar
            ),
            ["infinito-state/docs_sites"],
        )


if __name__ == "__main__":
    unittest.main()
