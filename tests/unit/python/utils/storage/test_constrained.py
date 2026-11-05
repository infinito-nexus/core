import subprocess
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path
from types import SimpleNamespace

from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VARIANTS,
    ROLE_FILE_VARS_MAIN,
)
from utils.storage import constrained
from utils.storage.constrained import (
    StorageDeclarationError,
    closure_storage,
    is_constrained,
    required_storage_bytes,
)

_GIB = 1024**3
_GB = 10**9
_USAGE = SimpleNamespace(free=123 * _GIB)

_ROLES = {
    "svc-db-store": "store:\n  enabled: true\n  shared: true\n  min_storage: 5GB\n",
    "web-app-shop": (
        "shop:\n  enabled: true\n  min_storage: 1GB\n"
        "cache:\n  enabled: true\n  mem_limit: 1g\n  min_storage: 3GB\n"
        "store:\n  enabled: true\n  shared: true\n"
    ),
    "web-app-odd": "odd:\n  enabled: true\n  min_storage: plenty\n",
}
_SHOP_VARIANTS = "- {}\n- services:\n    cache:\n      enabled: false\n"


class TestClosureStorage(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        roles_dir = Path(self._tmp.name) / "roles"
        for role, services in _ROLES.items():
            (roles_dir / role / ROLE_FILE_VARS_MAIN).parent.mkdir(parents=True)
            (roles_dir / role / ROLE_FILE_META_SERVICES).parent.mkdir(parents=True)
            (roles_dir / role / ROLE_FILE_VARS_MAIN).write_text(
                f"application_id: {role}\n", encoding="utf-8"
            )
            (roles_dir / role / ROLE_FILE_META_SERVICES).write_text(
                services, encoding="utf-8"
            )
        (roles_dir / "web-app-shop" / ROLE_FILE_META_VARIANTS).write_text(
            _SHOP_VARIANTS, encoding="utf-8"
        )
        self.measure = closure_storage(roles_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_an_unlisted_provider_is_not_walked(self) -> None:
        self.assertEqual(self.measure(["web-app-shop"], {}), {"web-app-shop": 4 * _GB})

    def test_a_listed_provider_counts_once_on_its_own(self) -> None:
        self.assertEqual(
            self.measure(["web-app-shop", "svc-db-store"], {}),
            {"web-app-shop": 4 * _GB, "svc-db-store": 5 * _GB},
        )

    def test_the_round_variant_drops_a_sidecar_it_switches_off(self) -> None:
        self.assertEqual(
            self.measure(["web-app-shop"], {"web-app-shop": 1}),
            {"web-app-shop": 1 * _GB},
        )

    def test_a_role_without_application_config_declares_nothing(self) -> None:
        self.assertEqual(
            self.measure(["svc-swarm-absent"], {}), {"svc-swarm-absent": 0}
        )

    def test_an_unparsable_declaration_is_refused_by_name(self) -> None:
        with self.assertRaisesRegex(
            StorageDeclarationError, r"web-app-odd: .*odd='plenty'"
        ):
            self.measure(["web-app-shop", "web-app-odd"], {})


class TestDockerDataRoot(unittest.TestCase):
    def test_a_daemon_that_does_not_answer_fails_closed(self) -> None:
        with (
            mock.patch.object(
                constrained.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=1),
            ),
            self.assertRaisesRegex(RuntimeError, "did not answer"),
        ):
            constrained.docker_data_root()

    def test_docker_info_runs_under_a_timeout(self) -> None:
        done = SimpleNamespace(returncode=0, stdout="/var/lib/docker\n", stderr="")
        with mock.patch.object(constrained.subprocess, "run", return_value=done) as run:
            constrained.docker_data_root()
        self.assertEqual(
            run.call_args.kwargs["timeout"], constrained.DOCKER_INFO_TIMEOUT_S
        )


class TestResolvedDockerRootFreeBytes(unittest.TestCase):
    def test_a_resolvable_root_is_measured(self) -> None:
        with (
            mock.patch.object(constrained, "docker_data_root", return_value="/"),
            mock.patch.object(
                constrained.shutil, "disk_usage", return_value=_USAGE
            ) as usage,
        ):
            self.assertEqual(constrained.resolved_docker_root_free_bytes(), _USAGE.free)
        usage.assert_called_once_with("/")

    def test_a_root_that_does_not_resolve_here_is_refused(self) -> None:
        with (
            mock.patch.object(
                constrained, "docker_data_root", return_value="/var/lib/docker-absent"
            ),
            self.assertRaisesRegex(RuntimeError, "docker-absent"),
        ):
            constrained.resolved_docker_root_free_bytes()

    def test_an_unreachable_parent_is_refused(self) -> None:
        with (
            mock.patch.object(constrained, "docker_data_root", return_value="/x"),
            mock.patch.object(
                constrained.shutil,
                "disk_usage",
                side_effect=PermissionError("denied"),
            ),
            self.assertRaisesRegex(RuntimeError, "denied"),
        ):
            constrained.resolved_docker_root_free_bytes()


class TestIsConstrained(unittest.TestCase):
    def test_need_above_free_is_constrained(self):
        self.assertTrue(
            is_constrained(free_bytes=122 * _GIB, required_bytes=381 * _GIB)
        )

    def test_need_equal_to_free_fits(self):
        self.assertFalse(
            is_constrained(free_bytes=100 * _GIB, required_bytes=100 * _GIB)
        )

    def test_need_below_free_fits(self):
        self.assertFalse(
            is_constrained(free_bytes=300 * _GIB, required_bytes=113 * _GIB)
        )

    def test_undeclared_need_never_constrains(self):
        self.assertFalse(is_constrained(free_bytes=1, required_bytes=0))


class TestRequiredStorageBytes(unittest.TestCase):
    def test_unknown_role_declares_nothing(self):
        self.assertEqual(required_storage_bytes(["web-app-does-not-exist"]), 0)

    def test_empty_selection_declares_nothing(self):
        self.assertEqual(required_storage_bytes([]), 0)

    def test_a_real_role_declares_a_positive_need(self):
        self.assertGreater(required_storage_bytes(["svc-db-mariadb"]), 0)

    def test_dependencies_are_counted_once_across_apps(self):
        single = required_storage_bytes(["svc-db-mariadb"])
        twice = required_storage_bytes(["svc-db-mariadb", "svc-db-mariadb"])
        self.assertEqual(single, twice)


class TestDockerRootFreeBytes(unittest.TestCase):
    """The daemon reports its data root in ITS namespace, which need not be ours.

    A caller running inside a container of that daemon sees a path that does not
    resolve, which used to raise FileNotFoundError out of shutil.disk_usage and
    abort the nested swarm drill of every workspace job.
    """

    def test_resolvable_root_is_measured_directly(self):
        with (
            mock.patch.object(constrained, "docker_data_root", return_value="/"),
            mock.patch.object(
                constrained.shutil, "disk_usage", return_value=_USAGE
            ) as usage,
        ):
            self.assertEqual(
                constrained.docker_root_free_bytes(local_vantage="/nonexistent"),
                _USAGE.free,
            )
        usage.assert_called_once_with("/")

    def test_unresolvable_root_falls_to_the_local_vantage(self):
        with (
            mock.patch.object(
                constrained, "docker_data_root", return_value="/var/lib/docker-absent"
            ),
            mock.patch.object(
                constrained.shutil, "disk_usage", return_value=_USAGE
            ) as usage,
        ):
            self.assertEqual(
                constrained.docker_root_free_bytes(local_vantage="/"),
                _USAGE.free,
            )
        usage.assert_called_once_with("/")

    def test_unreachable_daemon_still_raises(self):
        with (
            mock.patch.object(
                constrained, "docker_data_root", side_effect=RuntimeError("no daemon")
            ),
            self.assertRaises(RuntimeError),
        ):
            constrained.docker_root_free_bytes(local_vantage="/")

    def test_local_vantage_has_no_default(self):
        with self.assertRaises(TypeError):
            constrained.docker_root_free_bytes()


if __name__ == "__main__":
    unittest.main()
