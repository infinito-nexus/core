import unittest

from ansible.errors import AnsibleFilterError

from plugins.filter.merge.mapping import merge_mapping


class TestMergeMappingFilter(unittest.TestCase):
    def test_basic_merge_overwrites_and_adds(self):
        list1 = [
            {"source": "a", "target": 1},
            {"source": "b", "target": 2},
        ]
        list2 = [
            {"source": "b", "target": 3},
            {"source": "c", "target": 4},
        ]
        result = merge_mapping(list1, list2, "source")
        result_dict = {item["source"]: item["target"] for item in result}
        self.assertEqual(result_dict, {"a": 1, "b": 3, "c": 4})

    def test_merge_preserves_and_overwrites_fields(self):
        list1 = [{"source": "x", "value": 100, "flag": True}]
        list2 = [{"source": "x", "value": 200, "note": "updated"}]
        result = merge_mapping(list1, list2, "source")
        self.assertEqual(len(result), 1)
        merged = result[0]
        self.assertEqual(merged["value"], 200)
        self.assertTrue(merged["flag"])
        self.assertEqual(merged["note"], "updated")

    def test_empty_lists_return_empty(self):
        self.assertEqual(merge_mapping([], [], "source"), [])

    def test_missing_key_raises_error(self):
        list1 = [{"target": "no_source"}]
        list2 = []
        with self.assertRaises(AnsibleFilterError):
            merge_mapping(list1, list2, "source")

    def test_non_list_inputs_raise_error(self):
        with self.assertRaises(AnsibleFilterError):
            merge_mapping("not a list", [], "source")
        with self.assertRaises(AnsibleFilterError):
            merge_mapping([], "not a list", "source")


if __name__ == "__main__":
    unittest.main()
