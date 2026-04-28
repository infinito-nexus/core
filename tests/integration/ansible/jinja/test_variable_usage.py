import logging
import re
import unittest
from pathlib import Path

import yaml

from utils.cache.files import (
    iter_project_files,
    iter_project_files_with_content,
    read_text,
)
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_DEFAULTS_MAIN, ROLE_FILE_VARS_MAIN

logger = logging.getLogger(__name__)


class TestTopLevelVariableUsage(unittest.TestCase):
    def setUp(self):
        from . import PROJECT_ROOT

        self.project_root = str(PROJECT_ROOT)

        roles_prefix = str(Path(self.project_root) / "roles") + "/"
        group_vars_prefix = str(Path(self.project_root) / "group_vars" / "all") + "/"

        roles_vars: list[str] = []
        roles_defaults: list[str] = []
        group_vars: list[str] = []
        for path_str in iter_project_files(extensions=(".yml",)):
            if path_str.startswith(roles_prefix):
                tail = path_str[len(roles_prefix) :]
                if tail.endswith(f"/{ROLE_FILE_VARS_MAIN}") and tail.count("/") == 2:
                    roles_vars.append(path_str)
                elif (
                    tail.endswith(f"/{ROLE_FILE_DEFAULTS_MAIN}")
                    and tail.count("/") == 2
                ):
                    roles_defaults.append(path_str)
            elif (
                path_str.startswith(group_vars_prefix)
                and "/" not in path_str[len(group_vars_prefix) :]
            ):
                group_vars.append(path_str)

        self.roles_vars_paths = roles_vars + roles_defaults
        self.group_vars_paths = group_vars
        self.all_variable_files = self.roles_vars_paths + self.group_vars_paths
        self.valid_extensions = (
            ".yml",
            ".yaml",
            ".j2",
            ".py",
            ".sh",
            ".conf",
            ".env",
            ".xml",
            ".html",
            ".txt",
        )
        # Global Ansible runtime knobs are consumed by Ansible itself and may not
        # appear as plain string references inside this repository.
        # Namespace keys like default_users and defaults_applications are organizational
        # containers and are not directly referenced.
        self.ignored_top_level_keys = {
            "ansible_python_interpreter",
            "ansible_shell_executable",
            "default_users",
            "defaults_applications",
        }

    def get_top_level_keys(self, file_path):
        try:
            data = load_yaml_str(read_text(file_path))
        except yaml.YAMLError as e:
            logger.warning("Failed to parse YAML file '%s': %s", file_path, e)
            return []
        if isinstance(data, dict):
            return list(data.keys())
        return []

    def find_declaration_line(self, file_path, varname):
        """
        Find the 1-based line number where the top-level key is actually declared.
        """
        pattern = re.compile(rf"^\s*{re.escape(varname)}\s*:")
        for i, line in enumerate(read_text(file_path).splitlines(), 1):
            if pattern.match(line) and not line.lstrip().startswith("#"):
                return i
        return None

    def find_usage_in_project(self, varname, definition_path):
        """
        Search the whole project for varname, skipping only the single
        declaration line in definition_path. Walk and file contents are
        served from the process-level cache in utils.cache.files.
        """
        decl_line = self.find_declaration_line(definition_path, varname)

        for path, content in iter_project_files_with_content(
            extensions=self.valid_extensions
        ):
            # Fast pre-check: if varname doesn't appear anywhere in the file,
            # skip the line-by-line scan entirely. Cheap on cached content.
            if varname not in content:
                continue

            if path != definition_path or decl_line is None:
                # No declaration line to exclude → any hit is a real usage.
                return True

            # Same file as the definition: skip exactly the declaration line.
            for i, line in enumerate(content.splitlines(), 1):
                if i == decl_line:
                    continue
                if varname in line:
                    return True
        return False

    def test_top_level_variable_usage(self):
        """
        Ensure every top-level variable in roles/*/{vars,defaults}/main.yml
        and group_vars/all/*.yml is referenced somewhere in the project
        (other than its own declaration line).
        """
        unused = []
        for varfile in self.all_variable_files:
            keys = self.get_top_level_keys(varfile)
            for key in keys:
                if key in self.ignored_top_level_keys:
                    continue
                if not self.find_usage_in_project(key, varfile):
                    unused.append((varfile, key))

        if unused:
            msg = "\n".join(
                f"{path}: unused top-level key '{key}'" for path, key in unused
            )
            self.fail(
                "The following top-level variables are defined but never used:\n" + msg
            )


if __name__ == "__main__":
    unittest.main()
