import glob
import unittest

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT


def find_application_ids():
    """
    Scans all roles/*/vars/main.yml files and collects application_id values.
    Returns a dict mapping application_id to list of file paths where it appears.
    """
    ids = {}
    pattern = str(PROJECT_ROOT / "roles" / "*" / ROLE_FILE_VARS_MAIN)

    for file_path in glob.glob(pattern):  # nocheck: project-walk
        data = load_yaml_any(file_path) or {}
        app_id = data.get("application_id")
        if app_id is not None:
            ids.setdefault(app_id, []).append(file_path)
    return ids


class TestUniqueApplicationId(unittest.TestCase):
    def test_application_ids_are_unique(self):
        ids = find_application_ids()
        duplicates = {app_id: paths for app_id, paths in ids.items() if len(paths) > 1}
        if duplicates:
            messages = []
            for app_id, paths in duplicates.items():
                file_list = "\n    ".join(paths)
                messages.append(
                    f"application_id '{app_id}' found in multiple files:\n    {file_list}"
                )
            self.fail("\n\n".join(messages))


if __name__ == "__main__":
    unittest.main(verbosity=2)
