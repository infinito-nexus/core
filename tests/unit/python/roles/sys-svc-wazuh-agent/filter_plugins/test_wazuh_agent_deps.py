import importlib.util
import unittest

from . import PROJECT_ROOT

_spec = importlib.util.spec_from_file_location(
    "wazuh_agent_deps",
    PROJECT_ROOT / "roles" / "sys-svc-wazuh-agent" / "filter_plugins" / "wazuh_agent_deps.py",
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

PINNED = {"curl": "a" * 64, "rpm": "b" * 64, ".gitignore": "c" * 64}


class TestWazuhAgentDepsProblems(unittest.TestCase):
    def problems(self, manifest_lines):
        return _module.wazuh_agent_deps_problems(manifest_lines, PINNED)

    def test_matching_tree_has_no_problems(self):
        manifest = ["curl " + "a" * 64, "rpm " + "b" * 64, ".gitignore " + "c" * 64]
        self.assertEqual(self.problems(manifest), [])

    def test_changed_library_is_named_with_both_hashes(self):
        manifest = ["curl " + "a" * 64, "rpm " + "d" * 64, ".gitignore " + "c" * 64]
        self.assertEqual(self.problems(manifest), [f"rpm: hash {'d' * 64}, pin {'b' * 64}"])

    def test_missing_library_is_named(self):
        manifest = ["curl " + "a" * 64, ".gitignore " + "c" * 64]
        self.assertEqual(self.problems(manifest), ["rpm: pinned but missing"])

    def test_extra_library_is_named_with_its_hash(self):
        manifest = ["curl " + "a" * 64, "rpm " + "b" * 64, ".gitignore " + "c" * 64, "lua " + "e" * 64]
        self.assertEqual(self.problems(manifest), [f"lua: not pinned, hash {'e' * 64}"])

    def test_every_problem_is_listed_sorted(self):
        manifest = ["rpm " + "d" * 64, "lua " + "e" * 64, ".gitignore " + "c" * 64]
        self.assertEqual(
            self.problems(manifest),
            ["curl: pinned but missing", f"lua: not pinned, hash {'e' * 64}", f"rpm: hash {'d' * 64}, pin {'b' * 64}"],
        )

    def test_blank_lines_are_ignored(self):
        manifest = ["", "curl " + "a" * 64, "rpm " + "b" * 64, ".gitignore " + "c" * 64, "  "]
        self.assertEqual(self.problems(manifest), [])

    def test_filter_is_registered(self):
        self.assertIn("wazuh_agent_deps_problems", _module.FilterModule().filters())


if __name__ == "__main__":
    unittest.main()
