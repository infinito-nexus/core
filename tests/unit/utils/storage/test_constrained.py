import unittest
from unittest import mock

from utils.storage import constrained
from utils.storage.constrained import (
    docker_data_root_free_bytes,
    is_constrained,
    required_storage_bytes,
)

_GIB = 1024**3


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


class TestDockerDataRootFreeBytes(unittest.TestCase):
    def test_reported_root_is_measured(self):
        usage = mock.Mock(free=7 * _GIB)
        with (
            mock.patch.object(constrained, "docker_data_root", return_value="/data"),
            mock.patch.object(
                constrained.shutil, "disk_usage", return_value=usage
            ) as disk_usage,
        ):
            self.assertEqual(docker_data_root_free_bytes(), 7 * _GIB)
        disk_usage.assert_called_once_with("/data")

    def test_root_outside_the_mount_namespace_falls_back_to_this_filesystem(self):
        def usage(path):
            if path == "/var/lib/docker":
                raise FileNotFoundError(2, "No such file or directory")
            return mock.Mock(free=5 * _GIB)

        with (
            mock.patch.object(
                constrained, "docker_data_root", return_value="/var/lib/docker"
            ),
            mock.patch.object(constrained.shutil, "disk_usage", side_effect=usage),
        ):
            self.assertEqual(docker_data_root_free_bytes(), 5 * _GIB)


if __name__ == "__main__":
    unittest.main()
