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


class TestMetaRolesIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.invokable_items = get_invokable_paths()

        cls.playbook_contents = {}
        for path in STAGES_DIR.rglob("*.yml"):  # nocheck: project-walk
            cls.playbook_contents[path] = read_text(str(path))

        cls.include_pattern = re.compile(
            r'include_tasks:\s*["\']?\./tasks/utils/setup/group\.yml["\']?'
        )

        stage_lookup = re.compile(
            r"lookup\(\s*['\"]stage_groups['\"]\s*,\s*['\"](?P<stage>[a-z]+)['\"]"
        )
        cls.lookup_referenced = set()
        for content in cls.playbook_contents.values():
            for match in stage_lookup.finditer(content):
                cls.lookup_referenced.update(stage_groups(match.group("stage")))

    def test_each_invokable_item_referenced_in_playbooks(self):
        """
        Each invokable item must be either:
        - resolved by a `lookup('stage_groups', '<stage>')` loop, or
        - named in the loop of a stage that includes ./tasks/utils/setup/group.yml.
        """
        not_referenced = []
        for item in self.invokable_items:
            found = item in self.lookup_referenced
            loop_entry = re.compile(rf"-\s*{re.escape(item)}\b")
            for content in self.playbook_contents.values():
                if found:
                    break
                if self.include_pattern.search(content) and loop_entry.search(content):
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
