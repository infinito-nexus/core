import unittest
import yaml

from utils.cache.files import iter_project_files, read_text


class TestYamlSyntax(unittest.TestCase):
    def test_all_yml_files_are_valid_yaml(self):
        """
        Walk the entire repository, find all *.yml files and try to parse them
        with yaml.safe_load(). Fail the test if any file contains invalid YAML.
        """
        invalid = []

        for full in iter_project_files(extensions=(".yml",)):
            try:
                yaml.safe_load(read_text(full))
            except yaml.YAMLError as e:
                invalid.append((full, str(e)))
            except Exception as e:
                invalid.append((full, f"Unexpected error: {e}"))

        if invalid:
            msg_lines = [
                f"{path}: {err.splitlines()[0]}"  # just the first line of the error
                for path, err in invalid
            ]
            self.fail(
                "Found invalid YAML in the following files:\n" + "\n".join(msg_lines)
            )


if __name__ == "__main__":
    unittest.main()
