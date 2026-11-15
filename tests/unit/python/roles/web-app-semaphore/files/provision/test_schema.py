from __future__ import annotations

import unittest

from ._fake_provision import INTERFACE, load

schema = load("provision.schema")


class TestCheck(unittest.TestCase):
    def test_each_keyword_is_enforced(self):
        cases = [
            (1, {"type": "string"}, ""),
            (True, {"type": "integer"}, ""),
            ("c", {"enum": ["a", "b"]}, ""),
            ("a\n", {"pattern": "^a$"}, ""),
            ({}, {"required": ["x"]}, "x"),
            ({}, {"minProperties": 1}, ""),
            ({"y": 1}, {"additionalProperties": False}, "y"),
            ({"y": 1}, {"additionalProperties": {"type": "string"}}, "y"),
            ({"Y": 1}, {"propertyNames": {"pattern": "^[a-z]$"}}, "Y"),
            ({"x": {"z": 1}}, {"properties": {"x": {"required": ["w"]}}}, "x.w"),
        ]
        for document, rule, path in cases:
            with self.subTest(rule=rule):
                with self.assertRaises(schema.SchemaError) as caught:
                    schema.check(document, rule)
                self.assertEqual(caught.exception.path, path)

    def test_a_valid_document_passes(self):
        rule = {"type": "object", "required": ["a"], "properties": {"a": {"enum": [1]}}}
        self.assertIsNone(schema.check({"a": 1}, rule))

    def test_an_unsupported_keyword_is_refused(self):
        with self.assertRaisesRegex(schema.SchemaError, "unsupported keywords"):
            schema.check("x", {"minLength": 2})

    def test_the_interface_uses_supported_keywords_only(self):
        def keywords(rule):
            found = set(rule)
            for name in ("properties", "$defs"):
                for child in rule.get(name, {}).values():
                    found |= keywords(child)
            for name in ("additionalProperties", "propertyNames"):
                if isinstance(rule.get(name), dict):
                    found |= keywords(rule[name])
            return found

        self.assertLessEqual(keywords(INTERFACE), schema.KEYWORDS | schema.ANNOTATIONS)
        self.assertNotIn("$defs", schema.definition(INTERFACE, "inputs"))


if __name__ == "__main__":
    unittest.main()
