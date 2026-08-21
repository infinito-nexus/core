import unittest

from utils.sizes import to_bytes

try:
    from ansible.errors import AnsibleError
except Exception:
    AnsibleError = Exception


class TestToBytes(unittest.TestCase):
    def test_none_and_empty_return_none(self):
        self.assertIsNone(to_bytes(None))
        self.assertIsNone(to_bytes(""))

    def test_numeric_passthrough(self):
        self.assertEqual(to_bytes(1024), 1024)
        self.assertEqual(to_bytes(2.0), 2)

    def test_decimal_si_units(self):
        self.assertEqual(to_bytes("512m"), 512_000_000)
        self.assertEqual(to_bytes("2g"), 2_000_000_000)
        self.assertEqual(to_bytes("1k"), 1000)

    def test_binary_iec_units(self):
        self.assertEqual(to_bytes("2GiB"), 2 * 1024**3)
        self.assertEqual(to_bytes("1KiB"), 1024)

    def test_bare_number_is_bytes(self):
        self.assertEqual(to_bytes("100"), 100)

    def test_invalid_unit_raises(self):
        with self.assertRaises(AnsibleError):
            to_bytes("12x")

    def test_unparseable_raises(self):
        with self.assertRaises(AnsibleError):
            to_bytes("not-a-size")

    def test_unsupported_type_raises(self):
        with self.assertRaises(AnsibleError):
            to_bytes(["1g"])


if __name__ == "__main__":
    unittest.main()
