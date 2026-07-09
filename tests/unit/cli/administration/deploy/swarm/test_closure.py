"""Unit tests for cli.administration.deploy.swarm.closure."""

from __future__ import annotations

import importlib.util
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from utils import PROJECT_ROOT


def _load_closure():
    spec = importlib.util.spec_from_file_location(
        "cli_swarm_closure",
        str(PROJECT_ROOT / "cli/administration/deploy/swarm/closure.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


closure = _load_closure()


class _BaseClosureCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _write_inv(self, name: str, body: str) -> str:
        path = self.root / name
        path.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
        return str(path)

    def _write_roles(self, *names: str) -> Path:
        roles_dir = self.root / "roles"
        roles_dir.mkdir(exist_ok=True)
        for n in names:
            (roles_dir / n).mkdir(exist_ok=True)
        return roles_dir


class TestIsSwarmInventory(_BaseClosureCase, unittest.TestCase):
    def test_true_when_manager_group_present(self) -> None:
        path = self._write_inv(
            "swarm.yml",
            """
            all:
              children:
                svc-swarm-manager:
                  hosts:
                    mgr-01: {}
            """,
        )
        self.assertTrue(closure.is_swarm_inventory(path))

    def test_false_for_compose(self) -> None:
        path = self._write_inv(
            "compose.yml",
            """
            all:
              children:
                web-app-mediawiki:
                  hosts:
                    single-host: {}
            """,
        )
        self.assertFalse(closure.is_swarm_inventory(path))


class TestSwarmInfraClosure(_BaseClosureCase, unittest.TestCase):
    def test_returns_only_inventory_present_placement_roles(self) -> None:
        path = self._write_inv(
            "swarm.yml",
            """
            all:
              children:
                svc-swarm-manager:
                  hosts: { mgr-01: {} }
                svc-registry-docker:
                  hosts: { mgr-01: {} }
                svc-registry-cache:
                  hosts: { mgr-01: {} }
            """,
        )
        with mock.patch.object(
            closure,
            "iter_roles_with_placement",
            return_value=[
                "svc-registry-cache",
                "svc-db-mariadb",
                "svc-registry-docker",
                "svc-prx-openresty",
            ],
        ):
            result = closure.swarm_infra_closure(path)
        self.assertEqual(result, ["svc-registry-cache", "svc-registry-docker"])

    def test_empty_for_compose_inventory(self) -> None:
        path = self._write_inv(
            "compose.yml",
            """
            all:
              children:
                web-app-mediawiki:
                  hosts: { single-host: {} }
            """,
        )
        with mock.patch.object(
            closure,
            "iter_roles_with_placement",
            return_value=["svc-registry-docker"],
        ):
            self.assertEqual(closure.swarm_infra_closure(path), [])


class TestInventoryRoleGroups(_BaseClosureCase, unittest.TestCase):
    def test_returns_intersection_of_inventory_groups_and_roles_dir(self) -> None:
        path = self._write_inv(
            "inv.yml",
            """
            all:
              children:
                svc-swarm-node:
                  hosts: { mgr-01: {} }
                svc-swarm-manager:
                  hosts: { mgr-01: {} }
                svc-storage-nfs-server:
                  hosts: { nfs-01: {} }
                web-app-mediawiki:
                  hosts: { mgr-01: {} }
                custom-host-group:
                  hosts: { mgr-01: {} }
            """,
        )
        roles_dir = self._write_roles(
            "svc-swarm-node",
            "svc-storage-nfs-server",
            "web-app-mediawiki",
            "svc-db-mariadb",
        )
        result = closure.inventory_role_groups(path, roles_dir=roles_dir)
        self.assertEqual(
            result,
            ["svc-storage-nfs-server", "svc-swarm-node", "web-app-mediawiki"],
        )

    def test_excludes_non_role_groups(self) -> None:
        path = self._write_inv(
            "inv.yml",
            """
            all:
              children:
                svc-swarm-manager:
                  hosts: { mgr-01: {} }
                svc-swarm-node:
                  hosts: { mgr-01: {} }
            """,
        )
        roles_dir = self._write_roles("svc-swarm-node")
        result = closure.inventory_role_groups(path, roles_dir=roles_dir)
        self.assertEqual(result, ["svc-swarm-node"])


class TestSwarmDeployTargets(_BaseClosureCase, unittest.TestCase):
    """Cover the layered closure: seed -> dep-walk -> safety net."""

    def _make_swarm_inv(self, extra_groups: dict[str, list[str]] | None = None) -> str:
        body_lines = [
            "all:",
            "  children:",
            "    svc-swarm-node:",
            "      hosts: { mgr-01: {} }",
            "    svc-swarm-manager:",
            "      hosts: { mgr-01: {} }",
            "    web-app-mediawiki:",
            "      hosts: { mgr-01: {} }",
        ]
        if extra_groups:
            for group, hosts in extra_groups.items():
                body_lines.append(f"    {group}:")
                body_lines.append("      hosts:")
                body_lines.extend(f"        {h}: {{}}" for h in hosts)
        return self._write_inv("swarm.yml", "\n".join(body_lines) + "\n")

    def _patches(
        self,
        *,
        dep_walked: list[str] | None = None,
        placement: list[str] | None = None,
    ):
        return [
            mock.patch.object(
                closure,
                "_dep_walk_closure",
                side_effect=lambda seed, roles_dir=None: list(dep_walked or seed),
            ),
            mock.patch.object(
                closure,
                "iter_roles_with_placement",
                return_value=list(placement or []),
            ),
        ]

    def test_seed_from_inventory_when_no_operator_ids(self) -> None:
        path = self._make_swarm_inv(
            extra_groups={
                "svc-storage-nfs-server": ["nfs-01"],
                "svc-db-mariadb": ["mgr-01"],
            }
        )
        roles_dir = self._write_roles(
            "svc-swarm-node",
            "svc-storage-nfs-server",
            "web-app-mediawiki",
            "svc-db-mariadb",
        )
        patches = self._patches(
            dep_walked=[
                "svc-swarm-node",
                "svc-storage-nfs-server",
                "web-app-mediawiki",
                "svc-db-mariadb",
            ],
            placement=[],
        )
        with patches[0], patches[1]:
            result = closure.swarm_deploy_targets(None, path, roles_dir=roles_dir)
        self.assertIn("svc-db-mariadb", result)
        self.assertIn("web-app-mediawiki", result)
        self.assertEqual(
            result[:4],
            [
                "svc-db-mariadb",
                "svc-storage-nfs-server",
                "svc-swarm-node",
                "web-app-mediawiki",
            ],
        )

    def test_operator_ids_seed_dep_walk(self) -> None:
        path = self._make_swarm_inv(extra_groups={"svc-db-mariadb": ["mgr-01"]})
        roles_dir = self._write_roles(
            "svc-swarm-node", "web-app-mediawiki", "svc-db-mariadb"
        )
        patches = self._patches(
            dep_walked=["web-app-mediawiki", "svc-db-mariadb"],
            placement=[],
        )
        with patches[0], patches[1]:
            result = closure.swarm_deploy_targets(
                ["web-app-mediawiki"], path, roles_dir=roles_dir
            )
        self.assertEqual(result, ["web-app-mediawiki", "svc-db-mariadb"])

    def test_operator_ids_dep_walked_not_in_inventory_dropped(self) -> None:
        """When `disable` removes a dep-walked role from the inventory,
        the closure must drop it so validate_application_ids doesn't reject
        the whole deploy.
        """
        path = self._make_swarm_inv()
        roles_dir = self._write_roles(
            "svc-swarm-node", "web-app-mediawiki", "svc-db-mariadb"
        )
        patches = self._patches(
            dep_walked=["web-app-mediawiki", "svc-db-mariadb"],
            placement=[],
        )
        with patches[0], patches[1]:
            result = closure.swarm_deploy_targets(
                ["web-app-mediawiki"], path, roles_dir=roles_dir
            )
        self.assertEqual(result, ["web-app-mediawiki"])

    def test_placement_safety_net_picks_up_inventory_extras(self) -> None:
        path = self._make_swarm_inv(extra_groups={"svc-registry-cache": ["mgr-01"]})
        roles_dir = self._write_roles(
            "svc-swarm-node",
            "web-app-mediawiki",
            "svc-registry-cache",
        )
        patches = self._patches(
            dep_walked=["svc-swarm-node", "web-app-mediawiki"],
            placement=["svc-registry-cache"],
        )
        with patches[0], patches[1]:
            result = closure.swarm_deploy_targets(None, path, roles_dir=roles_dir)
        self.assertIn("svc-registry-cache", result)
        self.assertIn("svc-swarm-node", result)
        self.assertIn("web-app-mediawiki", result)

    def test_no_postgres_when_mariadb_app_in_inventory(self) -> None:
        """Regression guard: with both DBs carrying placement:
        manager, the dep-walk must only include the DB the app actually
        depends on (mariadb in this case), not both."""
        path = self._make_swarm_inv(extra_groups={"svc-db-mariadb": ["mgr-01"]})
        roles_dir = self._write_roles(
            "svc-swarm-node",
            "web-app-mediawiki",
            "svc-db-mariadb",
            "svc-db-postgres",
        )
        patches = self._patches(
            dep_walked=["svc-swarm-node", "web-app-mediawiki", "svc-db-mariadb"],
            placement=["svc-db-mariadb", "svc-db-postgres"],
        )
        with patches[0], patches[1]:
            result = closure.swarm_deploy_targets(None, path, roles_dir=roles_dir)
        self.assertIn("svc-db-mariadb", result)
        self.assertNotIn("svc-db-postgres", result)

    def test_compose_inventory_no_safety_net(self) -> None:
        path = self._write_inv(
            "compose.yml",
            """
            all:
              children:
                web-app-mediawiki:
                  hosts: { single-host: {} }
            """,
        )
        roles_dir = self._write_roles("web-app-mediawiki", "svc-registry-cache")
        patches = self._patches(
            dep_walked=["web-app-mediawiki"],
            placement=["svc-registry-cache"],
        )
        with patches[0], patches[1]:
            result = closure.swarm_deploy_targets(None, path, roles_dir=roles_dir)
        self.assertEqual(result, ["web-app-mediawiki"])
        self.assertNotIn("svc-registry-cache", result)

    def test_operator_ids_take_precedence_no_dedup_loss(self) -> None:
        path = self._make_swarm_inv()
        roles_dir = self._write_roles(
            "svc-swarm-node", "svc-registry-docker", "web-app-mediawiki"
        )
        patches = self._patches(
            dep_walked=["svc-registry-docker", "web-app-mediawiki"],
            placement=["svc-registry-docker"],
        )
        with patches[0], patches[1]:
            result = closure.swarm_deploy_targets(
                ["svc-registry-docker", "web-app-mediawiki"], path, roles_dir=roles_dir
            )
        self.assertEqual(result, ["svc-registry-docker", "web-app-mediawiki"])


if __name__ == "__main__":
    unittest.main()
