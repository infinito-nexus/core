from __future__ import annotations

import importlib.util
import unittest

from ansible.errors import AnsibleFilterError

from . import PROJECT_ROOT

OWN = "infinito-forward"


def _load():
    path = PROJECT_ROOT / "roles/web-app-stalwart/filter_plugins/stalwart_forwards.py"
    spec = importlib.util.spec_from_file_location("stalwart_forwards", str(path))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class TestStalwartForwards(unittest.TestCase):
    def setUp(self):
        self.forwards = _load().stalwart_forwards

    def test_normalises_and_sorts_destinations(self):
        result = self.forwards(
            [{"address": "A@example.org", "destinations": ["Z@x.org", "b@x.org"]}]
        )
        self.assertEqual(
            result,
            [{"address": "a@example.org", "destinations": ["b@x.org", "z@x.org"]}],
        )

    def test_forward_to_itself_is_rejected(self):
        with self.assertRaises(AnsibleFilterError):
            self.forwards(
                [{"address": "a@example.org", "destinations": ["A@example.org"]}]
            )

    def test_empty_destinations_are_rejected(self):
        with self.assertRaises(AnsibleFilterError):
            self.forwards([{"address": "a@example.org", "destinations": []}])

    def test_repeated_address_is_rejected(self):
        entry = {"address": "a@example.org", "destinations": ["b@x.org"]}
        with self.assertRaises(AnsibleFilterError):
            self.forwards([entry, dict(entry)])

    def test_invalid_destination_is_rejected(self):
        with self.assertRaises(AnsibleFilterError):
            self.forwards(
                [{"address": "a@example.org", "destinations": ["not-an-address"]}]
            )


class TestForwardInclude(unittest.TestCase):
    def setUp(self):
        self.include = _load().stalwart_forward_include

    def test_active_user_script_is_included(self):
        scripts = [
            {"name": "roundcube", "isActive": True},
            {"name": OWN, "isActive": False},
        ]
        self.assertEqual(self.include(scripts, OWN, ""), "roundcube")

    def test_include_survives_while_the_forward_script_is_active(self):
        scripts = [
            {"name": "roundcube", "isActive": False},
            {"name": OWN, "isActive": True},
        ]
        own = 'require ["copy", "include"];\nredirect :copy "a@x.org";\ninclude :personal "roundcube";\n'
        self.assertEqual(self.include(scripts, OWN, own), "roundcube")

    def test_deleted_user_script_is_dropped(self):
        scripts = [{"name": OWN, "isActive": True}]
        own = 'require ["copy", "include"];\ninclude :personal "roundcube";\n'
        self.assertEqual(self.include(scripts, OWN, own), "")

    def test_no_scripts_include_nothing(self):
        self.assertEqual(self.include([], OWN, ""), "")


class TestForwardScript(unittest.TestCase):
    def setUp(self):
        self.script = _load().stalwart_forward_script

    def test_redirects_every_destination_with_copy(self):
        self.assertEqual(
            self.script(["a@x.org", "b@y.org"], ""),
            'require ["copy"];\nredirect :copy "a@x.org";\nredirect :copy "b@y.org";\n',
        )

    def test_includes_the_user_script_last(self):
        self.assertEqual(
            self.script(["a@x.org"], 'my "rules"'),
            'require ["copy", "include"];\nredirect :copy "a@x.org";\n'
            'include :personal "my \\"rules\\"";\n',
        )

    def test_rendered_include_is_read_back(self):
        module = _load()
        rendered = module.stalwart_forward_script(["a@x.org"], 'my "rules"')
        scripts = [
            {"name": 'my "rules"', "isActive": False},
            {"name": OWN, "isActive": True},
        ]
        self.assertEqual(
            module.stalwart_forward_include(scripts, OWN, rendered), 'my "rules"'
        )


if __name__ == "__main__":
    unittest.main()
