import unittest
import unittest.mock as mock
from types import SimpleNamespace

from utils.storage import constrained
from utils.storage.constrained import is_constrained, required_storage_bytes

_GIB = 1024**3
_USAGE = SimpleNamespace(free=123 * _GIB)


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
