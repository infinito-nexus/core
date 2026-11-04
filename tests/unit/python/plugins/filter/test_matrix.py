from __future__ import annotations

import unittest

from ansible.errors import AnsibleFilterError

from plugins.filter.matrix import FilterModule, mxid

SERVER = "matrix.example.com"


class TestMxid(unittest.TestCase):
    def test_a_localpart_and_a_server_become_a_user_id(self) -> None:
        self.assertEqual(mxid("administrator", SERVER), "@administrator:" + SERVER)

    def test_a_leading_sigil_is_accepted_once_and_not_doubled(self) -> None:
        self.assertEqual(mxid("@chatgptbot", SERVER), "@chatgptbot:" + SERVER)

    def test_the_result_is_lowercased_because_synapse_rejects_anything_else(
        self,
    ) -> None:
        self.assertEqual(
            mxid("Administrator", "Matrix.Example.COM"),
            "@administrator:matrix.example.com",
        )

    def test_an_onion_server_keeps_its_name(self) -> None:
        onion = "jq3cxczghznig7mzqbfy7jlznvi4pv7q53xul2ptvrnsosnfamkhjrid.onion"
        self.assertEqual(mxid("biber", onion), "@biber:" + onion)

    def test_an_empty_localpart_is_refused(self) -> None:
        with self.assertRaises(AnsibleFilterError):
            mxid("  ", SERVER)

    def test_a_missing_server_name_is_refused(self) -> None:
        with self.assertRaises(AnsibleFilterError) as caught:
            mxid("administrator", "")
        self.assertIn("administrator", str(caught.exception))

    def test_a_full_user_id_passed_as_the_localpart_is_refused(self) -> None:
        with self.assertRaises(AnsibleFilterError) as caught:
            mxid("@administrator:other.example", SERVER)
        self.assertIn("pass the bare name", str(caught.exception))

    def test_the_filter_is_registered_under_its_name(self) -> None:
        self.assertIs(FilterModule().filters()["mxid"], mxid)


if __name__ == "__main__":
    unittest.main()
