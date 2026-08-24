import unittest

from ansible.errors import AnsibleError

from plugins.lookup.path_absolute import LookupModule

_VARS = {"playbook_dir": "/opt/src/infinito"}


class TestPathAbsoluteLookup(unittest.TestCase):
    def setUp(self):
        self.lookup = LookupModule()

    def test_joins_whole_relative_path(self):
        out = self.lookup.run(
            ["roles/sys-svc-compose/tasks/utils/swarm/x.yml"], variables=_VARS
        )
        self.assertEqual(
            out, ["/opt/src/infinito/roles/sys-svc-compose/tasks/utils/swarm/x.yml"]
        )

    def test_matches_path_join_filter_result(self):
        whole = self.lookup.run(["roles/a/b.yml"], variables=_VARS)[0]
        split = self.lookup.run(["roles", "a", "b.yml"], variables=_VARS)[0]
        self.assertEqual(whole, split)
        self.assertEqual(whole, "/opt/src/infinito/roles/a/b.yml")

    def test_joins_term_with_variable_segment(self):
        out = self.lookup.run(["roles", "web-app-keycloak"], variables=_VARS)
        self.assertEqual(out, ["/opt/src/infinito/roles/web-app-keycloak"])

    def test_strips_surrounding_whitespace_and_slashes(self):
        out = self.lookup.run(["  roles/a/b.yml  "], variables=_VARS)
        self.assertEqual(out, ["/opt/src/infinito/roles/a/b.yml"])

    def test_missing_playbook_dir_raises(self):
        with self.assertRaises(AnsibleError):
            self.lookup.run(["roles/a.yml"], variables={})


if __name__ == "__main__":
    unittest.main()
