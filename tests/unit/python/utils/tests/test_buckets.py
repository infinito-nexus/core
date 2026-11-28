from __future__ import annotations

import unittest

from utils.tests.buckets import buckets, register


class _Carrier:
    value: int

    def test_reads_its_attribute(self) -> None:
        self.assertEqual(self.value, 7)


class TestBuckets(unittest.TestCase):
    def test_every_item_lands_in_exactly_one_bucket_in_order(self) -> None:
        items = [f"role-{index}" for index in range(23)]
        split = buckets(items, 5)
        self.assertEqual(len(split), 5)
        flat = [item for bucket in split for item in bucket]
        self.assertEqual(sorted(flat), sorted(items))
        self.assertEqual(len(flat), len(set(flat)))
        for bucket in split:
            self.assertEqual(list(bucket), [i for i in items if i in bucket])

    def test_buckets_are_balanced_to_one_item(self) -> None:
        sizes = [len(bucket) for bucket in buckets(range(23), 5)]
        self.assertLessEqual(max(sizes) - min(sizes), 1)

    def test_fewer_items_than_buckets_yield_no_empty_bucket(self) -> None:
        self.assertEqual(buckets(["a", "b"], 4), [("a",), ("b",)])

    def test_a_non_positive_count_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            buckets(["a"], 0)


class TestRegister(unittest.TestCase):
    def test_the_generated_class_is_a_test_case_bound_in_the_namespace(self) -> None:
        namespace: dict[str, object] = {"__name__": "tests.fake"}
        generated = register(namespace, "TestCarrier_bucket_0", _Carrier, value=7)
        self.assertIs(namespace["TestCarrier_bucket_0"], generated)
        self.assertTrue(issubclass(generated, unittest.TestCase))
        self.assertEqual(generated.__module__, "tests.fake")
        self.assertEqual(generated.__qualname__, "TestCarrier_bucket_0")
        result = unittest.TestResult()
        unittest.defaultTestLoader.loadTestsFromTestCase(generated).run(result)
        self.assertEqual((result.testsRun, result.failures, result.errors), (1, [], []))

    def test_a_name_collision_is_refused(self) -> None:
        namespace: dict[str, object] = {"__name__": "tests.fake"}
        register(namespace, "TestCarrier_bucket_0", _Carrier, value=7)
        with self.assertRaises(AssertionError):
            register(namespace, "TestCarrier_bucket_0", _Carrier, value=7)


if __name__ == "__main__":
    unittest.main()
