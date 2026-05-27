import unittest

# import the functions from your CLI script
from cli.build.include import build_dependency_graph, find_cycle


class TestCircularDependencies(unittest.TestCase):
    """
    Integration test: ensure there are no circular 'run_after' dependencies
    among the roles in the roles/ directory.
    """

    @classmethod
    def setUpClass(cls):
        from . import PROJECT_ROOT

        cls.roles_dir = str(PROJECT_ROOT / "roles")

    def test_no_circular_dependencies(self):
        # Build the dependency graph using the real roles/
        _graph, _in_degree, roles = build_dependency_graph(self.roles_dir)

        # Attempt to find a cycle in the run_after mapping
        cycle = find_cycle(roles)

        if cycle:
            # Format cycle as "A -> B -> C -> A"
            cycle_str = " -> ".join(cycle)
            self.fail(f"Circular dependency detected among roles: {cycle_str}")

        # If no cycle, this assertion will pass
        self.assertIsNone(cycle, "Expected no circular dependencies")


if __name__ == "__main__":
    unittest.main()
