import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from textwrap import dedent

from . import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.roles.dependency_resolver import RoleDependencyResolver
from utils.roles.mapping import (
    ROLE_FILE_META_MAIN,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TASKS_MAIN,
)


def write(path: str, content: str):
    Path(str(Path(path).parent)).mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8") as f:
        f.write(dedent(content).lstrip())


def make_role(roles_dir: str, name: str):
    path = str(Path(roles_dir) / name)
    Path(path).mkdir(parents=True, exist_ok=True)
    Path(str(Path(path) / "tasks")).mkdir(parents=True, exist_ok=True)
    Path(str(Path(path) / "meta")).mkdir(parents=True, exist_ok=True)
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
            str(Path(self.roles_dir) / "A" / ROLE_FILE_TASKS_MAIN),
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
            str(Path(self.roles_dir) / "A" / ROLE_FILE_TASKS_MAIN),
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
            str(Path(self.roles_dir) / "A" / ROLE_FILE_TASKS_MAIN),
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
            str(Path(self.roles_dir) / "A" / ROLE_FILE_META_MAIN),
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

        # Per run_after lives at
        # meta/services.yml.<primary_entity>.run_after; for "A" the entity
        # name equals the role name.
        write(
            str(Path(self.roles_dir) / "A" / ROLE_FILE_META_SERVICES),
            """
            ---
            A:
              run_after:
                - J
                - K
            """,
        )
        write(
            str(Path(self.roles_dir) / "A" / ROLE_FILE_META_MAIN),
            """
            ---
            dependencies: []
            """,
        )

        r = RoleDependencyResolver(self.roles_dir)

        # Direkter Helper
        ra = r._extract_meta_run_after(str(Path(self.roles_dir) / "A"))
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
            str(Path(self.roles_dir) / "A" / ROLE_FILE_TASKS_MAIN),
            """
            - include_role:
                name: B
            """,
        )
        write(
            str(Path(self.roles_dir) / "B" / ROLE_FILE_TASKS_MAIN),
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
            str(Path(self.roles_dir) / "ROOT" / ROLE_FILE_TASKS_MAIN),
            """
            - include_role: { name: C1 }
            - import_role:  { name: C2 }
            """,
        )
        write(
            str(Path(self.roles_dir) / "ROOT" / ROLE_FILE_META_MAIN),
            """
            ---
            dependencies:
              - D1
              - { role: D2 }
            """,
        )
        # Per run_after lives at
        # meta/services.yml.<primary_entity>.run_after.
        write(
            str(Path(self.roles_dir) / "ROOT" / ROLE_FILE_META_SERVICES),
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
