#!/usr/bin/env python3
import os
import unittest
import tempfile
import shutil
import yaml
from cli.build.role_include import build_dependency_graph, topological_sort, gen_condi_role_incl

class TestGeneratePlaybook(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory to simulate roles
        self.temp_dir = tempfile.mkdtemp()

        # Define mock roles and dependencies
        self.roles = {
            'role-a': {'run_after': [], 'application_id': 'a'},
            'role-b': {'run_after': ['role-a'], 'application_id': 'b'},
            'role-c': {'run_after': ['role-b'], 'application_id': 'c'},
            'role-d': {'run_after': [], 'application_id': 'd'},
        }

        for role_name, meta in self.roles.items():
            role_path = os.path.join(self.temp_dir, role_name)
            os.makedirs(os.path.join(role_path, 'meta'), exist_ok=True)
            os.makedirs(os.path.join(role_path, 'vars'), exist_ok=True)

            # In the new layout (req-010) run_after lives at
            # meta/services.yml.<primary_entity>.run_after. For role names
            # that are not prefixed by a known category (e.g. 'role-a'),
            # get_entity_name returns the role name itself.
            meta_services = {
                role_name: {
                    'run_after': meta['run_after'],
                }
            }

            vars_file = {
                'application_id': meta['application_id']
            }

            with open(os.path.join(role_path, 'meta', 'services.yml'), 'w') as f:
                yaml.dump(meta_services, f)

            # find_roles() still uses meta/main.yml as a marker file to
            # detect roles, so we create an empty one here.
            with open(os.path.join(role_path, 'meta', 'main.yml'), 'w') as f:
                yaml.dump({}, f)

            with open(os.path.join(role_path, 'vars', 'main.yml'), 'w') as f:
                yaml.dump(vars_file, f)

    def tearDown(self):
        # Clean up the temporary directory
        shutil.rmtree(self.temp_dir)

    def test_dependency_graph_and_sort(self):
        graph, in_degree, roles = build_dependency_graph(self.temp_dir)

        self.assertIn('role-a', graph)
        self.assertIn('role-b', graph)
        self.assertEqual(graph['role-a'], ['role-b'])
        self.assertEqual(graph['role-b'], ['role-c'])
        self.assertEqual(graph['role-c'], [])
        self.assertEqual(in_degree['role-c'], 1)
        self.assertEqual(in_degree['role-b'], 1)
        self.assertEqual(in_degree['role-a'], 0)
        self.assertEqual(in_degree['role-d'], 0)

        sorted_roles = topological_sort(graph, in_degree)
        # The expected order must be a → b → c, d can be anywhere before or after
        self.assertTrue(sorted_roles.index('role-a') < sorted_roles.index('role-b') < sorted_roles.index('role-c'))

    def test_gen_condi_role_incl(self):
        entries = gen_condi_role_incl(self.temp_dir)

        text = ''.join(entries)
        self.assertIn("setup a", text)
        self.assertIn("setup b", text)
        self.assertIn("setup c", text)
        self.assertIn("setup d", text)

        # Order must preserve run_after
        a_index = text.index("setup a")
        b_index = text.index("setup b")
        c_index = text.index("setup c")
        self.assertTrue(a_index < b_index < c_index)

if __name__ == '__main__':
    unittest.main()
