import re
import unittest
from pathlib import Path

import yaml

from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_all_str

from . import PROJECT_ROOT


class TestIncludeImportExistence(unittest.TestCase):
    """
    Every include_role / import_role name must resolve to a directory under roles/,
    and every include_tasks / import_tasks file reference must resolve to an existing
    YAML file either locally (same dir as the referencing file), globally (from repo
    root), or under the top-level tasks/ directory.
    """

    def setUp(self):
        self.project_root = str(PROJECT_ROOT)
        self.roles_dir = str(Path(self.project_root) / "roles")

        self.files_to_scan = [
            filepath
            for filepath in iter_project_files(extensions=(".yml",), exclude_tests=True)
            if "/.git/" not in filepath
        ]

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
                        refs.extend(
                            item[value_key]
                            for item in val
                            if isinstance(item, dict) and value_key in item
                        )
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
                documents = list(load_yaml_all_str(text))
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
                        f"  • Extracted name value: {role_name!r}\n"
                        "The 'name:' field must contain a non-empty string.\n"
                        "Example:\n"
                        "  include_role:\n"
                        "    name: my-role-name\n"
                    )

                pattern = re.sub(r"\{\{.*?\}\}", "*", role_name)
                roles_root = Path(self.roles_dir)
                if "*" in pattern or "?" in pattern:
                    matches = [p for p in roles_root.glob(pattern) if p.is_dir()]
                else:
                    candidate = roles_root / pattern
                    matches = [candidate] if candidate.is_dir() else []
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
            file_dir = str(Path(file_path).parent)

            role_name = None
            role_path_dir = None
            if self.roles_dir in file_dir:
                parts = list(Path(file_dir).parts)
                idx = parts.index("roles")
                if idx + 1 < len(parts):
                    role_name = parts[idx + 1]
                    role_path_dir = str(Path(self.roles_dir) / role_name)

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
                if not Path(pattern_ref).suffix:
                    pattern_ref += ".yml"

                # Resolve relative to each candidate base. ``pattern_ref``
                # may be relative or absolute; once it sits under ``base``
                # we either expand wildcards via :meth:`Path.glob` or
                # check for a literal file. The project-walk lint flags
                # rglob/os.walk/glob.glob — neither is used here.
                has_wildcard = "*" in pattern_ref or "?" in pattern_ref
                matches: list[str] = []
                if Path(pattern_ref).is_absolute():
                    candidates = [Path(pattern_ref)]
                    if has_wildcard:
                        # Absolute pattern with wildcards: split off the
                        # leading literal directory and glob from there.
                        anchor = Path(pattern_ref).anchor
                        relative = Path(pattern_ref).relative_to(anchor)
                        matches.extend(
                            str(p)
                            for p in Path(anchor).glob(str(relative))
                            if p.is_file()
                        )
                    elif candidates[0].is_file():
                        matches.append(str(candidates[0]))
                else:
                    for base in (
                        Path(file_dir),
                        Path(self.project_root),
                        Path(self.project_root) / "tasks",
                    ):
                        if has_wildcard:
                            matches.extend(
                                str(p) for p in base.glob(pattern_ref) if p.is_file()
                            )
                        else:
                            candidate = base / pattern_ref
                            if candidate.is_file():
                                matches.append(str(candidate))

                if not matches:
                    missing.append((file_path, task_ref))

        if missing:
            messages = [
                f"File '{fp}' references missing task file '{tr}'" for fp, tr in missing
            ]
            self.fail("\n".join(messages))


if __name__ == "__main__":
    unittest.main()
