import os
import re
import unittest
from collections import defaultdict
from pathlib import Path

from utils.annotations.suppress import is_suppressed_anywhere
from utils.cache.files import iter_project_files, read_text
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

from . import PROJECT_ROOT

ROLES_DIR = str(PROJECT_ROOT / "roles")
ROOT_TASKS_DIR = str(PROJECT_ROOT / "tasks")


def is_under_root_tasks(fpath):
    abs_path = str(Path(fpath).resolve())
    return abs_path.startswith(str(Path(ROOT_TASKS_DIR).resolve()) + os.sep)


def find_role_includes(roles_dir):
    """
    Scan all YAML files under `roles_dir`, skipping any under a top-level `tasks/` directory,
    and yield (filepath, line_number, role_name) for each literal import_role/include_role
    usage. Dynamic includes using Jinja variables (e.g. {{ ... }}) are ignored.
    """
    roles_prefix = str(Path(roles_dir).resolve()) + os.sep
    root_tasks_prefix = str(Path(ROOT_TASKS_DIR).resolve()) + os.sep
    for fpath in iter_project_files(extensions=(".yml", ".yaml")):
        resolved = str(Path(fpath).resolve())
        if not resolved.startswith(roles_prefix):
            continue
        if resolved.startswith(root_tasks_prefix):
            continue

        try:
            lines = read_text(fpath).splitlines(keepends=True)
        except (OSError, UnicodeDecodeError):
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
    """Return True iff the role's tasks define a ``run_once_<key>`` flag
    or carry the unified ``# nocheck: run-once`` opt-out marker.
    """
    key = role_name.replace("-", "_")
    if re.search(rf"\brun_once_{re.escape(key)}\b", content, re.IGNORECASE):
        return True
    return is_suppressed_anywhere(content.splitlines(), "run-once")


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
            role_tasks = str(Path(ROLES_DIR) / role_name / ROLE_FILE_TASKS_MAIN)
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
                    f'  → For example, add "# nocheck: run-once" at the top of {role_tasks} to suppress this warning.\n'
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
