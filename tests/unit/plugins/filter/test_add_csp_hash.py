import unittest

from ansible.errors import AnsibleFilterError

from plugins.filter.csp_filters import FilterModule

add_csp_hash = FilterModule.add_csp_hash


class TestAddCspHash(unittest.TestCase):
    def setUp(self):
        self.current = {
            "app1": {"script-src-elem": ["existing-hash"]},
        }

    def test_appends_new_hash_without_mutating_input(self):
        result = add_csp_hash(self.current, "app1", "script-src-elem", "new-hash")
        self.assertEqual(
            result["app1"]["script-src-elem"], ["existing-hash", "new-hash"]
        )
        # Original input must remain unchanged
        self.assertEqual(self.current["app1"]["script-src-elem"], ["existing-hash"])

    def test_does_not_duplicate_existing_hash(self):
        result = add_csp_hash(self.current, "app1", "script-src-elem", "existing-hash")
        self.assertEqual(result["app1"]["script-src-elem"], ["existing-hash"])

    def test_creates_missing_application_entry(self):
        result = add_csp_hash(self.current, "app2", "script-src-elem", "code")
        self.assertEqual(result["app2"], {"script-src-elem": ["code"]})
        # Existing app entry preserved
        self.assertEqual(result["app1"]["script-src-elem"], ["existing-hash"])

    def test_creates_missing_directive(self):
        result = add_csp_hash(self.current, "app1", "style-src-elem", "code")
        self.assertEqual(result["app1"]["style-src-elem"], ["code"])
        self.assertEqual(result["app1"]["script-src-elem"], ["existing-hash"])

    def test_none_current_treated_as_empty(self):
        result = add_csp_hash(None, "app1", "script-src-elem", "code")
        self.assertEqual(result, {"app1": {"script-src-elem": ["code"]}})

    def test_empty_dict_current(self):
        result = add_csp_hash({}, "app1", "script-src-elem", "code")
        self.assertEqual(result, {"app1": {"script-src-elem": ["code"]}})

    def test_filter_registered_in_filter_module(self):
        filters = FilterModule().filters()
        self.assertIn("add_csp_hash", filters)
        self.assertIs(filters["add_csp_hash"], FilterModule.add_csp_hash)

    def test_raises_on_invalid_input(self):
        # Passing a non-iterable snippet list via broken current should raise
        with self.assertRaises(AnsibleFilterError):
            add_csp_hash(
                {"app1": {"script-src-elem": 123}}, "app1", "script-src-elem", "code"
            )


if __name__ == "__main__":
    unittest.main()
