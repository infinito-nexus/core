import unittest
from unittest.mock import patch

from cli.core.git import git_clean_repo


class TestGit(unittest.TestCase):
    def test_git_clean_repo_invokes_git_clean(self):
        with patch("cli.core.git.subprocess.run") as mock_run:
            git_clean_repo()
            mock_run.assert_called_once_with(["git", "clean", "-Xfd"], check=True)


if __name__ == "__main__":
    unittest.main()
