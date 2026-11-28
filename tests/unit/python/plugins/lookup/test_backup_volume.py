import importlib.util
import unittest
import unittest.mock as mock
from types import ModuleType
from typing import ClassVar

from ansible.errors import AnsibleError

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


def _run(
    module: ModuleType,
    applications: dict,
    variables: dict | None = None,
    templar: object | None = None,
    terms: list[str] | None = None,
) -> list[str]:
    loader = mock.MagicMock()
    loader.get.return_value.run.return_value = [applications]
    with mock.patch.object(module, "lookup_loader", loader):
        plugin = module.LookupModule()
        if templar is not None:
            plugin._templar = templar
        return plugin.run(terms, variables=variables or {})[0]


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

    def test_a_nameless_entry_gets_the_project_prefix(self) -> None:
        apps = {"r": {"volumes": {"semantic": {"backup": False}}}}
        self.assertEqual(_run(type(self)._module, apps), ["r_semantic"])

    def test_the_docs_cache_is_excluded_under_its_deployed_name(self) -> None:
        """web-app-docs pins no ``name:``, so the engine calls its volume
        ``docs_docs_sites``. Emitting the bare key left the 17 GB regenerable
        site tree in the backup and filled the runner's container root."""
        apps = {"web-app-docs": {"volumes": {"docs_sites": {"backup": False}}}}
        self.assertEqual(_run(type(self)._module, apps), ["docs_docs_sites"])

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


class TestCodeDerivedTerm(unittest.TestCase):
    APPS: ClassVar[dict] = {
        "web-app-docs": {
            "volumes": {"docs_sites": {"backup": False, "derived": "code"}},
        },
        "web-svc-loki": {
            "volumes": {"data": {"name": "loki_data", "backup": False}},
        },
        "r": {
            "volumes": {
                "index": {"name": "r_index", "backup": False, "derived": "state"},
            },
        },
    }

    @classmethod
    def setUpClass(cls) -> None:
        cls._module = _load_module()

    def test_only_code_derived_volumes_under_their_deployed_name(self) -> None:
        self.assertEqual(
            _run(type(self)._module, self.APPS, terms=["derived"]),
            ["docs_docs_sites"],
        )

    def test_negative_control_without_the_term_every_opt_out_is_listed(self) -> None:
        self.assertEqual(
            _run(type(self)._module, self.APPS),
            ["docs_docs_sites", "loki_data", "r_index"],
        )

    def test_the_pinned_docker_name_wins_for_a_derived_volume(self) -> None:
        apps = {
            "r": {
                "volumes": {
                    "v": {"name": "pinned", "backup": False, "derived": "code"},
                }
            }
        }
        self.assertEqual(_run(type(self)._module, apps, terms=["derived"]), ["pinned"])

    def test_a_host_without_derived_volumes_gets_an_empty_list(self) -> None:
        apps = {"web-svc-loki": self.APPS["web-svc-loki"]}
        self.assertEqual(_run(type(self)._module, apps, terms=["derived"]), [])

    def test_an_unknown_term_is_refused(self) -> None:
        with self.assertRaises(AnsibleError):
            _run(type(self)._module, self.APPS, terms=["code"])


class TestSwarmNfsExclusion(unittest.TestCase):
    """In swarm mode with NFS storage the export host's repo captures the
    NFS-backed volumes, so the volume backup must skip them; manager-pinned
    roles keep node-local volumes and stay covered here."""

    SWARM_NFS: ClassVar[dict] = {
        "DEPLOYMENT_MODE": "swarm",
        "IS_COMPOSE_MODE": False,
        "IS_SWARM_MODE": True,
        "storage": {"backend": "nfs"},
        "groups": {"svc-bkp-nfs-2-local": ["nfs-server"]},
    }

    @classmethod
    def setUpClass(cls) -> None:
        cls._module = _load_module()

    def test_nfs_backed_volumes_are_excluded_in_swarm(self) -> None:
        apps = {
            "web-app-nextcloud": {
                "volumes": {"data": {"name": "nextcloud_data"}},
            },
            "web-svc-seaweedfs": {
                "volumes": {"data": {"name": "seaweedfs_data"}},
            },
        }
        self.assertEqual(
            _run(type(self)._module, apps, variables=dict(self.SWARM_NFS)),
            ["nextcloud_data"],
        )

    def test_compose_mode_excludes_nothing(self) -> None:
        apps = {"web-app-nextcloud": {"volumes": {"data": {"name": "nextcloud_data"}}}}
        self.assertEqual(
            _run(
                type(self)._module,
                apps,
                variables={"DEPLOYMENT_MODE": "compose", "storage": {"backend": "nfs"}},
            ),
            [],
        )

    def test_an_nfs_opt_out_stays_covered(self) -> None:
        apps = {
            "web-app-nextcloud": {
                "volumes": {"data": {"name": "kept_local", "nfs": False}},
            }
        }
        self.assertEqual(
            _run(type(self)._module, apps, variables=dict(self.SWARM_NFS)), []
        )

    def test_the_deployment_mode_expression_is_templated(self) -> None:
        """group_vars/all/18_swarm.yml defines DEPLOYMENT_MODE as a Jinja
        expression, so the raw value never equals 'swarm'. Comparing it
        unrendered silently disables the whole exclusion."""
        expression = (
            "{{ 'swarm' if (groups['svc-swarm-node'] | default([]) | length) > 1"
            " else 'compose' }}"
        )
        rendered = {expression: "swarm"}
        templar = mock.Mock()
        templar.template.side_effect = lambda value: rendered.get(value, value)
        apps = {"web-app-nextcloud": {"volumes": {"data": {"name": "nextcloud_data"}}}}
        self.assertEqual(
            _run(
                type(self)._module,
                apps,
                variables={**self.SWARM_NFS, "DEPLOYMENT_MODE": expression},
                templar=templar,
            ),
            ["nextcloud_data"],
        )

    def test_a_role_forcing_compose_keeps_its_volumes_covered(self) -> None:
        """compose_mode_force overrides the cluster mode for ONE role. The
        lookup answers for every role at once, so an ambient value must not
        exclude a role that is not on the export - web-app-bigbluebutton runs
        compose-mode in a swarm cluster and its volumes stay node-local."""
        apps = {
            "web-app-bigbluebutton": {
                "volumes": {"database": {"name": "bigbluebutton_database"}},
            },
            "web-app-nextcloud": {
                "volumes": {"data": {"name": "nextcloud_data"}},
            },
        }
        self.assertEqual(
            _run(
                type(self)._module,
                apps,
                variables={
                    "compose_mode_force": "compose",
                    **dict(self.SWARM_NFS),
                },
            ),
            ["nextcloud_data"],
        )

    def test_without_the_export_repo_nothing_is_excluded(self) -> None:
        """svc-bkp-nfs-2-local enters a play by inventory group membership
        alone, and svc-storage-nfs-server ships a variant that runs without
        it. Excluding on storage.backend alone would leave those volumes with
        no capture at all."""
        apps = {"web-app-nextcloud": {"volumes": {"data": {"name": "nextcloud_data"}}}}
        variables = {k: v for k, v in self.SWARM_NFS.items() if k != "groups"}
        self.assertEqual(_run(type(self)._module, apps, variables=variables), [])

    def test_an_empty_export_repo_group_does_not_exclude(self) -> None:
        apps = {"web-app-nextcloud": {"volumes": {"data": {"name": "nextcloud_data"}}}}
        variables = {**self.SWARM_NFS, "groups": {"svc-bkp-nfs-2-local": []}}
        self.assertEqual(_run(type(self)._module, apps, variables=variables), [])

    def test_a_config_entry_is_never_excluded_by_the_nfs_rule(self) -> None:
        apps = {
            "web-app-nextcloud": {
                "volumes": {
                    "loader": {"name": "nc_loader", "type": "config"},
                    "data": {"name": "nextcloud_data"},
                }
            }
        }
        self.assertEqual(
            _run(type(self)._module, apps, variables=dict(self.SWARM_NFS)),
            ["nextcloud_data"],
        )

    def test_backup_false_still_excludes_without_swarm(self) -> None:
        apps = {"r": {"volumes": {"v": {"name": "gone", "backup": False}}}}
        self.assertEqual(
            _run(
                type(self)._module,
                apps,
                variables={
                    "DEPLOYMENT_MODE": "compose",
                    "IS_COMPOSE_MODE": True,
                    "IS_SWARM_MODE": False,
                    "storage": {"backend": "local"},
                },
            ),
            ["gone"],
        )


if __name__ == "__main__":
    unittest.main()
