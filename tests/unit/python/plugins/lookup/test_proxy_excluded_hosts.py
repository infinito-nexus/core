import unittest

from plugins.lookup.proxy_excluded_hosts import merge_excluded

LOOPBACK = ["127.0.0.1", "::1", "localhost"]


class TestMergeExcluded(unittest.TestCase):
    def test_the_object_store_follows_the_loopback_forms(self) -> None:
        self.assertEqual(
            ["127.0.0.1", "::1", "localhost", "seaweedfs"],
            merge_excluded(LOOPBACK, "seaweedfs"),
        )

    def test_no_object_store_leaves_the_loopback_forms_alone(self) -> None:
        self.assertEqual(LOOPBACK, merge_excluded(LOOPBACK, ""))

    def test_every_loopback_form_survives(self) -> None:
        for form in LOOPBACK:
            with self.subTest(form=form):
                self.assertIn(form, merge_excluded(LOOPBACK, "seaweedfs"))

    def test_an_object_store_named_like_loopback_is_not_duplicated(self) -> None:
        self.assertEqual(LOOPBACK, merge_excluded(LOOPBACK, "localhost"))

    def test_the_caller_list_is_not_mutated(self) -> None:
        original = list(LOOPBACK)
        merge_excluded(original, "seaweedfs")
        self.assertEqual(LOOPBACK, original)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
