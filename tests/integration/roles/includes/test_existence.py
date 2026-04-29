import unittest
import os
import glob
import yaml
import re

from utils.cache.files import read_text


class TestIncludeImportExistence(unittest.TestCase):
    """
    Every include_role / import_role name must resolve to a directory under roles/,
    and every include_tasks / import_tasks file reference must resolve to an existing
    YAML file either locally (same dir as the referencing file), globally (from repo
    root), or under the top-level tasks/ directory.
    """

    def setUp(self):
        tests_dir = os.path.dirname(__file__)
        self.project_root = os.path.abspath(
            os.path.join(tests_dir, os.pardir, os.pardir, os.pardir, os.pardir)
        )
        self.roles_dir = os.path.join(self.project_root, "roles")

        self.files_to_scan = []
        for filepath in glob.glob(
            os.path.join(self.project_root, "**", "*.yml"), recursive=True
        ):
            if "/.git/" in filepath or "/tests/" in filepath:
                continue
            self.files_to_scan.append(filepath)

    @staticmethod
    def _collect_refs(data, directive_keys, value_key):
        """
        Recursively collect referenced names/paths under any of ``directive_keys``.

        Handles three syntaxes:
          scalar:     key: value
          block:      key: { <value_key>: value }
          block-list: key: [ { <value_key>: v1 }, { <value_key>: v2 } ]
        """
        refs = []
        if isinstance(data, dict):
            for key, val in data.items():
                if key in directive_keys:
                    if isinstance(val, str):
                        refs.append(val)
                    elif isinstance(val, dict) and value_key in val:
                        refs.append(val[value_key])
                    elif isinstance(val, list):
                        for item in val:
                            if isinstance(item, dict) and value_key in item:
                                refs.append(item[value_key])
                else:
                    refs.extend(
                        TestIncludeImportExistence._collect_refs(
                            val, directive_keys, value_key
                        )
                    )
        elif isinstance(data, list):
            for item in data:
                refs.extend(
                    TestIncludeImportExistence._collect_refs(
                        item, directive_keys, value_key
                    )
                )
        return refs

    def _iter_docs(self):
        """Yield (file_path, doc) for every non-empty YAML document across the scan set."""
        for file_path in self.files_to_scan:
            try:
                text = read_text(file_path)
            except (OSError, UnicodeDecodeError):
                continue
            try:
                documents = list(yaml.safe_load_all(text))
            except yaml.YAMLError:
                self.fail(f"Failed to parse YAML in {file_path}")
            for doc in documents:
                if doc is None:
                    continue
                yield file_path, doc

    def test_include_import_roles_exist(self):
        missing = []
        for file_path, doc in self._iter_docs():
            for role_name in self._collect_refs(
                doc, ("include_role", "import_role"), "name"
            ):
                if not isinstance(role_name, str) or not role_name.strip():
                    self.fail(
                        "Invalid include_role/import_role name detected.\n"
                        f"  • File: {file_path}\n"
                        f"  • Extracted name value: {repr(role_name)}\n"
                        "The 'name:' field must contain a non-empty string.\n"
                        "Example:\n"
                        "  include_role:\n"
                        "    name: my-role-name\n"
                    )

                pattern = re.sub(r"\{\{.*?\}\}", "*", role_name)
                glob_path = os.path.join(self.roles_dir, pattern)

                matches = [p for p in glob.glob(glob_path) if os.path.isdir(p)]
                if not matches:
                    missing.append((file_path, role_name))

        if missing:
            messages = [
                f"File '{fp}' references missing role '{rn}'" for fp, rn in missing
            ]
            self.fail("\n".join(messages))

    def test_include_import_tasks_exist(self):
        missing = []
        for file_path, doc in self._iter_docs():
            file_dir = os.path.dirname(file_path)

            role_name = None
            role_path_dir = None
            if self.roles_dir in file_dir:
                parts = file_dir.split(os.sep)
                idx = parts.index("roles")
                if idx + 1 < len(parts):
                    role_name = parts[idx + 1]
                    role_path_dir = os.path.join(self.roles_dir, role_name)

            for task_ref in self._collect_refs(
                doc, ("include_tasks", "import_tasks"), "file"
            ):
                pattern_ref = task_ref
                if "{{ role_path }}" in pattern_ref and role_path_dir:
                    pattern_ref = pattern_ref.replace("{{ role_path }}", role_path_dir)
                if "{{ playbook_dir }}" in pattern_ref:
                    pattern_ref = pattern_ref.replace(
                        "{{ playbook_dir }}", self.project_root
                    )
                pattern_ref = re.sub(r"\{\{.*?\}\}", "*", pattern_ref)
                if not os.path.splitext(pattern_ref)[1]:
                    pattern_ref += ".yml"

                local_glob = os.path.join(file_dir, pattern_ref)
                global_glob = os.path.join(self.project_root, pattern_ref)
                tasks_dir_glob = os.path.join(self.project_root, "tasks", pattern_ref)

                matches = []
                matches += [p for p in glob.glob(local_glob) if os.path.isfile(p)]
                matches += [p for p in glob.glob(global_glob) if os.path.isfile(p)]
                matches += [p for p in glob.glob(tasks_dir_glob) if os.path.isfile(p)]

                if not matches:
                    missing.append((file_path, task_ref))

        if missing:
            messages = [
                f"File '{fp}' references missing task file '{tr}'" for fp, tr in missing
            ]
            self.fail("\n".join(messages))


if __name__ == "__main__":
    unittest.main()
