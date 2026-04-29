import os
import unittest

from utils.cache.files import iter_project_files


class TestFilenameConventions(unittest.TestCase):
    """
    Integration test to ensure README.md and TODO.md files
    are always written in uppercase (README.md / TODO.md).
    """

    def test_readme_and_todo_filenames_are_uppercase(self):
        bad_files = []
        for path in iter_project_files():
            filename = os.path.basename(path)
            lower = filename.lower()
            if lower in ("readme.md", "todo.md"):
                if filename not in ("README.md", "TODO.md"):
                    bad_files.append(path)

        msg = (
            (
                "The following files violate uppercase naming convention "
                "(must be README.md or TODO.md):\n- " + "\n- ".join(bad_files)
            )
            if bad_files
            else None
        )

        self.assertEqual(bad_files, [], msg)


if __name__ == "__main__":
    unittest.main()
