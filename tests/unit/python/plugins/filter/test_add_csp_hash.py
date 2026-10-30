import unittest

from ansible.errors import AnsibleFilterError

from plugins.filter.csp_filters import FilterModule

add_csp_hash = FilterModule.add_csp_hash

CLEARNET = "app.example.org"
ONION = "app.exampleonionnodeaddress.onion"


class TestAddCspHash(unittest.TestCase):
    def setUp(self):
        self.current = {
            CLEARNET: {"script-src-elem": ["existing-hash"]},
            ONION: {},
        }

    def test_appends_new_hash_without_mutating_input(self):
        result = add_csp_hash(self.current, CLEARNET, "script-src-elem", "new-hash")
        self.assertEqual(
            result[CLEARNET]["script-src-elem"], ["existing-hash", "new-hash"]
        )
        self.assertEqual(self.current[CLEARNET]["script-src-elem"], ["existing-hash"])

    def test_does_not_duplicate_existing_hash(self):
        result = add_csp_hash(
            self.current, CLEARNET, "script-src-elem", "existing-hash"
        )
        self.assertEqual(result[CLEARNET]["script-src-elem"], ["existing-hash"])

    def test_fills_an_opened_vhost_entry(self):
        result = add_csp_hash(self.current, ONION, "script-src-elem", "code")
        self.assertEqual(result[ONION], {"script-src-elem": ["code"]})
        self.assertEqual(result[CLEARNET]["script-src-elem"], ["existing-hash"])

    def test_two_siblings_keep_their_own_snippets(self):
        result = {CLEARNET: {}, ONION: {}}
        result = add_csp_hash(result, CLEARNET, "script-src-elem", "clearnet-snippet")
        result = add_csp_hash(result, ONION, "script-src-elem", "onion-snippet")
        self.assertEqual(
            result,
            {
                CLEARNET: {"script-src-elem": ["clearnet-snippet"]},
                ONION: {"script-src-elem": ["onion-snippet"]},
            },
        )

    def test_creates_missing_directive(self):
        result = add_csp_hash(self.current, CLEARNET, "style-src-elem", "code")
        self.assertEqual(result[CLEARNET]["style-src-elem"], ["code"])
        self.assertEqual(result[CLEARNET]["script-src-elem"], ["existing-hash"])

    def test_vhost_without_injection_pass_fails(self):
        with self.assertRaises(AnsibleFilterError):
            add_csp_hash(self.current, "other.example.org", "script-src-elem", "code")

    def test_none_current_fails(self):
        with self.assertRaises(AnsibleFilterError):
            add_csp_hash(None, CLEARNET, "script-src-elem", "code")

    def test_empty_store_fails(self):
        with self.assertRaises(AnsibleFilterError):
            add_csp_hash({}, CLEARNET, "script-src-elem", "code")

    def test_filter_registered_in_filter_module(self):
        filters = FilterModule().filters()
        self.assertIn("add_csp_hash", filters)
        self.assertIs(filters["add_csp_hash"], FilterModule.add_csp_hash)

    def test_raises_on_invalid_input(self):
        with self.assertRaises(AnsibleFilterError):
            add_csp_hash(
                {CLEARNET: {"script-src-elem": 123}},
                CLEARNET,
                "script-src-elem",
                "code",
            )


if __name__ == "__main__":
    unittest.main()
