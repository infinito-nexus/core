import os
import sys
import shutil
import tempfile
import unittest
from textwrap import dedent

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from utils.roles.dependency_resolver import RoleDependencyResolver  # noqa: E402


def write(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(dedent(content).lstrip())


def make_role(roles_dir: str, name: str):
    path = os.path.join(roles_dir, name)
    os.makedirs(path, exist_ok=True)
    os.makedirs(os.path.join(path, "tasks"), exist_ok=True)
    os.makedirs(os.path.join(path, "meta"), exist_ok=True)
    return path


class TestRoleDependencyResolver(unittest.TestCase):
    def setUp(self):
        self.roles_dir = tempfile.mkdtemp(prefix="roles_")

    def tearDown(self):
        shutil.rmtree(self.roles_dir, ignore_errors=True)

    # ----------------------------- TESTS -----------------------------

    def test_include_and_import_literal(self):
        """
        A/tasks/main.yml:
          - include_role: { name: B }
          - import_role:  { name: C }
        Expect: deps = {B, C}
        """
        make_role(self.roles_dir, "A")
        make_role(self.roles_dir, "B")
        make_role(self.roles_dir, "C")

        write(
            os.path.join(self.roles_dir, "A", "tasks", "main.yml"),
            """
            - name: include B
              include_role:
                name: B

            - name: import C
              import_role:
                name: C
            """,
        )

        r = RoleDependencyResolver(self.roles_dir)
        deps = r.get_role_dependencies("A")
        self.assertEqual(deps, {"B", "C"})

    def test_loop_with_string_items_and_dict_items(self):
        """
        A/tasks/main.yml uses loop with strings and dicts.
        Expect: {D, E, F, G}
        """
        make_role(self.roles_dir, "A")
        for rn in ["D", "E", "F", "G"]:
            make_role(self.roles_dir, rn)

        write(
            os.path.join(self.roles_dir, "A", "tasks", "main.yml"),
            """
            - name: loop over strings → D, E
              include_role:
                name: "{{ item }}"
              loop:
                - D
                - E

            - name: loop over dicts → F, G
              import_role:
                name: "{{ item.role }}"
              with_items:
                - { role: "F" }
                - { role: "G" }
            """,
        )

        r = RoleDependencyResolver(self.roles_dir)
        deps = r.get_role_dependencies("A")
        self.assertEqual(deps, {"D", "E", "F", "G"})

    def test_pure_jinja_ignored_without_loop(self):
        """
        name: "{{ something }}" with no loop should be ignored.
        """
        make_role(self.roles_dir, "A")
        for rn in ["X", "Y"]:
            make_role(self.roles_dir, rn)

        write(
            os.path.join(self.roles_dir, "A", "tasks", "main.yml"),
            """
            - name: pure var ignored
              include_role:
                name: "{{ something }}"
            """,
        )

        r = RoleDependencyResolver(self.roles_dir)
        deps = r.get_role_dependencies("A")
        self.assertEqual(deps, set())

    def test_meta_dependencies_strings_and_dicts(self):
        """
        meta/main.yml:
          dependencies:
            - H
            - { role: I }
        Expect: {H, I}
        """
        make_role(self.roles_dir, "A")
        make_role(self.roles_dir, "H")
        make_role(self.roles_dir, "I")

        write(
            os.path.join(self.roles_dir, "A", "meta", "main.yml"),
            """
            ---
            dependencies:
              - H
              - { role: I }
            """,
        )

        r = RoleDependencyResolver(self.roles_dir)
        deps = r.get_role_dependencies("A")
        self.assertEqual(deps, {"H", "I"})

    def test_run_after_extraction_and_toggle(self):
        """
        galaxy_info.run_after is only included when resolve_run_after=True
        """
        make_role(self.roles_dir, "A")
        make_role(self.roles_dir, "J")
        make_role(self.roles_dir, "K")

        # Per req-010 run_after lives at
        # meta/services.yml.<primary_entity>.run_after; for "A" the entity
        # name equals the role name.
        write(
            os.path.join(self.roles_dir, "A", "meta", "services.yml"),
            """
            ---
            A:
              run_after:
                - J
                - K
            """,
        )
        write(
            os.path.join(self.roles_dir, "A", "meta", "main.yml"),
            """
            ---
            dependencies: []
            """,
        )

        r = RoleDependencyResolver(self.roles_dir)

        # Direkter Helper
        ra = r._extract_meta_run_after(os.path.join(self.roles_dir, "A"))
        self.assertEqual(ra, {"J", "K"})

        # Transitiv – off by default
        visited_off = r.resolve_transitively(["A"], resolve_run_after=False)
        self.assertNotIn("J", visited_off)
        self.assertNotIn("K", visited_off)

        # Transitiv – enabled
        visited_on = r.resolve_transitively(["A"], resolve_run_after=True)
        self.assertTrue({"A", "J", "K"}.issubset(visited_on))

    def test_cycle_and_max_depth(self):
        """
        A → include B
        B → import  A
        - Ensure cycle-safe traversal.
        - max_depth=0 → only start
        - max_depth=1 → start + direct deps
        """
        make_role(self.roles_dir, "A")
        make_role(self.roles_dir, "B")

        write(
            os.path.join(self.roles_dir, "A", "tasks", "main.yml"),
            """
            - include_role:
                name: B
            """,
        )
        write(
            os.path.join(self.roles_dir, "B", "tasks", "main.yml"),
            """
            - import_role:
                name: A
            """,
        )

        r = RoleDependencyResolver(self.roles_dir)

        visited = r.resolve_transitively(["A"])
        self.assertTrue({"A", "B"}.issubset(visited))

        only_start = r.resolve_transitively(["A"], max_depth=0)
        self.assertEqual(only_start, {"A"})

        depth_one = r.resolve_transitively(["A"], max_depth=1)
        self.assertEqual(depth_one, {"A", "B"})

    def test_resolve_transitively_combined_sources(self):
        """
        Combined test: include/import + dependencies (+ optional run_after).
        """
        for rn in ["ROOT", "C1", "C2", "D1", "D2", "RA1"]:
            make_role(self.roles_dir, rn)

        write(
            os.path.join(self.roles_dir, "ROOT", "tasks", "main.yml"),
            """
            - include_role: { name: C1 }
            - import_role:  { name: C2 }
            """,
        )
        write(
            os.path.join(self.roles_dir, "ROOT", "meta", "main.yml"),
            """
            ---
            dependencies:
              - D1
              - { role: D2 }
            """,
        )
        # Per req-010 run_after lives at
        # meta/services.yml.<primary_entity>.run_after.
        write(
            os.path.join(self.roles_dir, "ROOT", "meta", "services.yml"),
            """
            ---
            ROOT:
              run_after:
                - RA1
            """,
        )

        r = RoleDependencyResolver(self.roles_dir)

        # Ohne run_after
        visited = r.resolve_transitively(["ROOT"], resolve_run_after=False)
        for expected in ["ROOT", "C1", "C2", "D1", "D2"]:
            self.assertIn(expected, visited)
        self.assertNotIn("RA1", visited)

        # Mit run_after
        visited_ra = r.resolve_transitively(["ROOT"], resolve_run_after=True)
        self.assertIn("RA1", visited_ra)


if __name__ == "__main__":
    unittest.main()
