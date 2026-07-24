import re
import sys
import unittest

from plugins.filter.invokable_paths import get_invokable_paths
from utils.cache.files import read_text
from utils.roles.stage import stage_groups

from . import PROJECT_ROOT

ROOT = PROJECT_ROOT
sys.path.insert(0, str(ROOT))

STAGES_DIR = ROOT / "tasks" / "stages"
GROUPS_DIR = ROOT / "tasks" / "groups"


class TestMetaRolesIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.role_files = get_invokable_paths(suffix="-roles.yml")
        cls.invokable_items = get_invokable_paths()

        cls.playbook_contents = {}
        for path in STAGES_DIR.rglob("*.yml"):  # nocheck: project-walk
            cls.playbook_contents[path] = read_text(str(path))

        cls.include_pattern = re.compile(
            r'include_tasks:\s*["\']\./tasks/groups/\{\{\s*[A-Za-z_][A-Za-z0-9_]*\s*\}\}-roles\.yml["\']'
        )

        stage_lookup = re.compile(
            r"lookup\(\s*['\"]stage_groups['\"]\s*,\s*['\"](?P<stage>[a-z]+)['\"]"
        )
        cls.lookup_referenced = set()
        for content in cls.playbook_contents.values():
            for match in stage_lookup.finditer(content):
                cls.lookup_referenced.update(stage_groups(match.group("stage")))

    def test_all_role_files_exist(self):
        """Each '-roles.yml' path returned by the filter must exist in the project root."""
        missing = []
        for fname in self.role_files:
            path = GROUPS_DIR / fname
            if not path.is_file():
                missing.append(fname)
        self.assertFalse(
            missing, f"The following role files are missing at project root: {missing}"
        )

    def test_each_invokable_item_referenced_in_playbooks(self):
        """
        Each invokable item (without suffix) must be either:
        - resolved by a `lookup('stage_groups', '<stage>')` loop, or
        - looped through by a dynamic include_tasks ({{ item }}-roles.yml), or
        - referenced by a direct include_tasks to ./tasks/groups/<item>-roles.yml.
        """
        not_referenced = []
        for item in self.invokable_items:
            found = item in self.lookup_referenced
            loop_entry = re.compile(rf"-\s*{re.escape(item)}\b")
            direct_include = re.compile(
                rf'include_tasks:\s*["\']\./tasks/groups/{re.escape(item)}-roles\.yml["\']'
            )
            for content in self.playbook_contents.values():
                if found:
                    break
                dynamic_ref = self.include_pattern.search(
                    content
                ) and loop_entry.search(content)
                static_ref = direct_include.search(content)
                if dynamic_ref or static_ref:
                    found = True
                    break
            if not found:
                not_referenced.append(item)

        self.assertEqual(
            not_referenced,
            [],
            f"The following invokable items are not referenced in any playbook: {not_referenced}",
        )


if __name__ == "__main__":
    unittest.main()
