import re
import unittest
from pathlib import Path

import yaml

from utils.cache.files import iter_project_files
from utils.cache.yaml import load_yaml_all


def find_role_task_yml_files(root_dir):
    """Yield ``.yml`` / ``.yaml`` files under ``<root>/roles/*/tasks/``.

    Routes through the cached project walk so the search shares the same
    file list every other lint/integration test uses.
    """
    roles_prefix = str(Path(root_dir) / "roles") + "/"
    matches: list[str] = []
    for path_str in iter_project_files(extensions=(".yml", ".yaml")):
        if not path_str.startswith(roles_prefix):
            continue
        rel = path_str[len(roles_prefix) :].split("/")
        # roles/<role>/tasks/<file>
        if len(rel) == 3 and rel[1] == "tasks":
            matches.append(path_str)
    return matches


class RunOnceInclusionTest(unittest.TestCase):
    """
    Ensure that every Ansible block in roles/*/tasks with a when condition matching
    either the dynamic Jinja scheme or a literal run_once_<role_name> is not defined,
    and containing an include_role/import_role also ends with
    include_tasks:  as its last task.
    """

    WHEN_PATTERN = re.compile(
        r"(?:run_once_\+\s*\(role_name\s*\|\s*lower\s*\|\s*replace\('\-','\_'\)\)\s*is\s*(?:not\s+)?defined"
        r"|run_once_[a-z0-9_]+\s*is\s*(?:not\s+)?defined)",
        re.IGNORECASE,
    )

    def test_run_once_blocks(self):
        from . import PROJECT_ROOT

        project_root = str(PROJECT_ROOT)
        violations = []

        for filepath in find_role_task_yml_files(project_root):
            try:
                docs = list(load_yaml_all(filepath))
            except yaml.YAMLError as e:
                self.fail(f"Failed to parse YAML file {filepath}: {e}")

            for doc in docs:
                # Determine tasks list
                tasks = None
                if isinstance(doc, dict) and isinstance(doc.get("tasks"), list):
                    tasks = doc["tasks"]
                elif isinstance(doc, list):
                    tasks = doc
                if not tasks:
                    continue

                for item in tasks:
                    if not isinstance(item, dict) or "block" not in item:
                        continue
                    when = item.get("when")
                    if not isinstance(when, str) or not self.WHEN_PATTERN.search(when):
                        continue

                    block = item["block"]
                    # Check for include_role or import_role within block
                    has_role_include = any(
                        isinstance(t, dict)
                        and ("include_role" in t or "import_role" in t)
                        for t in block
                    )
                    # Check that block contains the run-once flag include_tasks anywhere
                    has_run_once_flag = any(
                        isinstance(t, dict)
                        and t.get("include_tasks") == "utils/once/flag.yml"
                        for t in block
                    )

                    if has_role_include and not has_run_once_flag:
                        violations.append(
                            f"{filepath}: block with when='{when}' missing final include_tasks: utils/once/flag.yml"
                        )

        if violations:
            self.fail(
                "Run-once blocks missing include_tasks:\n" + "\n".join(violations)
            )


if __name__ == "__main__":
    unittest.main()
