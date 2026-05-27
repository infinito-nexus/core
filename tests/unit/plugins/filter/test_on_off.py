import unittest

from plugins.filter.on_off import FilterModule
from plugins.filter.on_off import on_off as on_off_fn


class TestOnOffFilter(unittest.TestCase):
    def test_filters_registered(self):
        filters = FilterModule().filters()
        self.assertIn("on_off", filters)
        self.assertIs(filters["on_off"], on_off_fn)

    def test_native_booleans(self):
        self.assertEqual(on_off_fn(True), "on")
        self.assertEqual(on_off_fn(False), "off")

    def test_truthy_strings(self):
        for truthy in ("true", "TRUE", "True", "yes", "Yes", "on", "ON", "1", "y", "t"):
            with self.subTest(truthy=truthy):
                self.assertEqual(on_off_fn(truthy), "on")

    def test_falsy_strings(self):
        for falsy in (
            "false",
            "FALSE",
            "False",
            "no",
            "No",
            "off",
            "OFF",
            "0",
            "n",
            "f",
            "",
        ):
            with self.subTest(falsy=falsy):
                self.assertEqual(on_off_fn(falsy), "off")

    def test_numeric(self):
        self.assertEqual(on_off_fn(1), "on")
        self.assertEqual(on_off_fn(42), "on")
        self.assertEqual(on_off_fn(0), "off")
        self.assertEqual(on_off_fn(0.0), "off")
        self.assertEqual(on_off_fn(1.5), "on")

    def test_none(self):
        self.assertEqual(on_off_fn(None), "off")

    def test_unknown_string_raises(self):
        with self.assertRaises(ValueError):
            on_off_fn("maybe")
        with self.assertRaises(ValueError):
            on_off_fn("xyz")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
