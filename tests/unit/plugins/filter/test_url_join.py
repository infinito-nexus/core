import sys
import unittest
from pathlib import Path

# Ensure plugins/filter directory is on the path
sys.path.insert(
    0,
    str(
        Path(
            str(Path(str(Path(__file__).parent)) / "../../../../plugins/filter")
        ).resolve()
    ),
)

from ansible.errors import AnsibleFilterError
from url_join import url_join


class TestUrlJoinFilter(unittest.TestCase):
    # --- success cases (path only) ---
    def test_http_basic(self):
        self.assertEqual(
            url_join(["http://example.com", "foo", "bar"]), "http://example.com/foo/bar"
        )

    def test_https_slashes(self):
        self.assertEqual(
            url_join(["https://example.com/", "/api/", "/v1/", "/users/"]),
            "https://example.com/api/v1/users",
        )

    def test_custom_scheme(self):
        self.assertEqual(
            url_join(["myapp+v1://host/", "//section", "item"]),
            "myapp+v1://host/section/item",
        )

    def test_only_scheme(self):
        self.assertEqual(url_join(["https://"]), "https://")

    # --- success cases with query ---
    def test_query_normalization_first_q_then_amp(self):
        self.assertEqual(
            url_join(["https://example.com", "api", "?a=1", "&b=2"]),
            "https://example.com/api?a=1&b=2",
        )

    def test_query_ignores_given_prefix_order(self):
        self.assertEqual(
            url_join(["https://example.com", "?a=1", "?b=2", "&c=3"]),
            "https://example.com?a=1&b=2&c=3",
        )

    def test_query_after_path_with_slashes(self):
        self.assertEqual(
            url_join(["https://example.com/", "/x/", "y/", "?q=ok"]),
            "https://example.com/x/y?q=ok",
        )

    def test_query_with_numeric_value(self):
        self.assertEqual(
            url_join(["https://example.com", "?n=123"]), "https://example.com?n=123"
        )

    def test_none_in_list(self):
        self.assertEqual(
            url_join(["https://example.com", None, "foo", None, "?a=1", None]),
            "https://example.com/foo?a=1",
        )

    # --- error cases ---
    def test_none_input_raises(self):
        with self.assertRaisesRegex(
            AnsibleFilterError, r"parts must be a non-empty list; got None"
        ):
            url_join(None)

    def test_empty_list_raises(self):
        with self.assertRaisesRegex(
            AnsibleFilterError, r"parts must be a non-empty list"
        ):
            url_join([])

    def test_non_list_raises(self):
        with self.assertRaisesRegex(
            AnsibleFilterError, r"parts must be a list/tuple; got str"
        ):
            url_join("https://example.com")

    def test_first_none_raises(self):
        with self.assertRaisesRegex(
            AnsibleFilterError, r"first element must include a scheme"
        ):
            url_join([None, "foo"])

    def test_no_scheme_raises(self):
        with self.assertRaisesRegex(
            AnsibleFilterError, r"must start with '<scheme>://'"
        ):
            url_join(["example.com", "foo"])

    def test_additional_scheme_in_later_part_raises(self):
        with self.assertRaisesRegex(
            AnsibleFilterError, r"only the first element may contain a scheme"
        ):
            url_join(["https://example.com", "https://elsewhere"])

    def test_path_after_query_raises(self):
        with self.assertRaisesRegex(
            AnsibleFilterError, r"path element .* after query parameters started"
        ):
            url_join(["https://example.com", "?a=1", "still/path"])

    def test_query_element_empty_raises(self):
        with self.assertRaisesRegex(AnsibleFilterError, r"query element .* is empty"):
            url_join(["https://example.com", "?"])

    def test_query_element_multiple_pairs_raises(self):
        with self.assertRaisesRegex(
            AnsibleFilterError, r"must contain exactly one 'key=value' pair"
        ):
            url_join(["https://example.com", "?a=1&b=2"])

    def test_query_element_missing_equal_raises(self):
        with self.assertRaisesRegex(AnsibleFilterError, r"must match 'key=value'"):
            url_join(["https://example.com", "&a"])

    def test_query_element_bad_chars_raises(self):
        with self.assertRaisesRegex(AnsibleFilterError, r"must match 'key=value'"):
            url_join(["https://example.com", "?a#=1"])

    def test_unstringifiable_first_part_raises(self):
        class Bad:
            def __str__(self):
                raise ValueError("boom")

        with self.assertRaisesRegex(
            AnsibleFilterError, r"unable to convert part at index 0"
        ):
            url_join([Bad(), "x"])

    def test_unstringifiable_later_part_raises(self):
        class Bad:
            def __str__(self):
                raise ValueError("boom")

        with self.assertRaisesRegex(
            AnsibleFilterError, r"unable to convert part at index 3"
        ):
            url_join(["https://example.com", "ok", "?a=1", Bad()])


if __name__ == "__main__":
    unittest.main()
