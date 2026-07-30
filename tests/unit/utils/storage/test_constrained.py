import unittest

from utils.storage.constrained import is_constrained, required_storage_bytes

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


if __name__ == "__main__":
    unittest.main()
