import unittest

from ansible.errors import AnsibleError

import plugins.lookup.network_suffixes as suffixes_mod


class TestNetworkSuffixesLookup(unittest.TestCase):
    def test_every_registry_network_with_a_suffix_is_listed(self):
        self.assertEqual(suffixes_mod.LookupModule().run([])[0], {"tor": ".onion"})

    def test_a_term_fails_loudly(self):
        with self.assertRaises(AnsibleError):
            suffixes_mod.LookupModule().run(["tor"])


if __name__ == "__main__":
    unittest.main()
