import unittest
import os
import yaml
import logging
from glob import glob
import re

from utils.cache.files import iter_project_files_with_content, read_text


class TestTopLevelVariableUsage(unittest.TestCase):
    def setUp(self):
        self.project_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "../../../")
        )
        # Braces werden von glob nicht unterstützt – also einzeln sammeln:
        self.roles_vars_paths = glob(
            os.path.join(self.project_root, "roles/*/vars/main.yml")
        ) + glob(os.path.join(self.project_root, "roles/*/defaults/main.yml"))
        self.group_vars_paths = glob(
            os.path.join(self.project_root, "group_vars/all/*.yml")
        )
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
        self.ignored_top_level_keys = {
            "ansible_python_interpreter",
            "ansible_shell_executable",
        }

    def get_top_level_keys(self, file_path):
        try:
            data = yaml.safe_load(read_text(file_path))
        except yaml.YAMLError as e:
            logging.warning("Failed to parse YAML file '%s': %s", file_path, e)
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
