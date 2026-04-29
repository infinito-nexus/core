import os
import re
import unittest
from collections import defaultdict

from utils.cache.files import read_text

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
ROLES_DIR = os.path.join(PROJECT_ROOT, "roles")
ROOT_TASKS_DIR = os.path.join(PROJECT_ROOT, "tasks")


def is_under_root_tasks(fpath):
    abs_path = os.path.abspath(fpath)
    return abs_path.startswith(os.path.abspath(ROOT_TASKS_DIR) + os.sep)


def find_role_includes(roles_dir):
    """
    Scan all YAML files under `roles_dir`, skipping any under a top-level `tasks/` directory,
    and yield (filepath, line_number, role_name) for each literal import_role/include_role
    usage. Dynamic includes using Jinja variables (e.g. {{ ... }}) are ignored.
    """
    for dirpath, _, filenames in os.walk(roles_dir):
        for fname in filenames:
            if not fname.endswith((".yml", ".yaml")):
                continue

            fpath = os.path.join(dirpath, fname)
            # Skip any files under the root-level tasks/ directory
            if os.path.abspath(fpath).startswith(
                os.path.abspath(os.path.join(roles_dir, "..", "tasks")) + os.sep
            ):
                continue

            try:
                lines = read_text(fpath).splitlines(keepends=True)
            except (IOError, OSError, UnicodeDecodeError):
                continue

            for idx, line in enumerate(lines):
                if "import_role" not in line and "include_role" not in line:
                    continue

                base_indent = len(line) - len(line.lstrip())
                # Look ahead up to 5 lines for the associated `name:` entry
                for nxt in lines[idx + 1 : idx + 6]:
                    indent = len(nxt) - len(nxt.lstrip())
                    # Only consider more-indented lines (the block under import/include)
                    if indent <= base_indent:
                        continue
                    m = re.match(r'\s*name:\s*[\'"]?([A-Za-z0-9_\-]+)[\'"]?', nxt)
                    if not m:
                        continue

                    role_name = m.group(1)
                    # Ignore the generic "user" role include
                    if role_name == "user":
                        break

                    # Skip any dynamic includes using Jinja syntax
                    if "{{" in nxt or "}}" in nxt:
                        break

                    yield fpath, idx + 1, role_name
                    break


def check_run_once_tag(content, role_name):
    """
    Checks for run_once_{role_name} or # run_once_{role_name}: deactivated in content.
    """
    key = role_name.replace("-", "_")
    pattern = (
        rf"(run_once_{key})"
        rf"|(#\s*run_once_{key}: deactivated)"
    )
    return re.search(pattern, content, re.IGNORECASE)


class TestRunOnceTag(unittest.TestCase):
    def test_all_roles_have_run_once_tag(self):
        role_to_locations = defaultdict(list)

        # Collect all places where roles are included/imported
        for fpath, line, role_name in find_role_includes(ROLES_DIR):
            key = role_name.replace("-", "_")
            role_to_locations[key].append((fpath, line, role_name))

        errors = {}
        for key, usages in role_to_locations.items():
            # Only check the role's own tasks/main.yml instead of the includer file
            _, line, role_name = usages[0]
            role_tasks = os.path.join(ROLES_DIR, role_name, "tasks", "main.yml")
            try:
                content = read_text(role_tasks)
            except (FileNotFoundError, OSError):
                # Fallback to the includer file if tasks/main.yml doesn't exist
                includer_file = usages[0][0]
                content = read_text(includer_file)

            if not check_run_once_tag(content, role_name):
                error_msg = (
                    f'Role "{role_name}" is imported/included but no "run_once_{key}" tag or deactivation comment found.\n'
                    f"First usage at includer: {usages[0][0]}, line {line}\n"
                    f'  → Ensure "run_once_{key}" is defined in {role_tasks} or deactivate with comment.\n'
                    f'  → For example, add "# run_once_{key}: deactivated" at the top of {role_tasks} to suppress this warning.\n'
                    f"All occurrences:\n"
                    + "".join([f"  - {fp}, line {ln}\n" for fp, ln, _ in usages])
                )
                errors[key] = error_msg

        if errors:
            msg = (
                "Some included/imported roles are missing a run_once tag or deactivation comment:\n\n"
                + "\n".join(errors.values())
            )
            self.fail(msg)


if __name__ == "__main__":
    unittest.main()
