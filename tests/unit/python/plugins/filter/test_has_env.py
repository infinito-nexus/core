import shutil
import unittest
from pathlib import Path

from plugins.filter.has.env import has_env


class TestHasEnvFilter(unittest.TestCase):
    def setUp(self):
        self.base_dir = "./testdata"
        self.app_with_env = "app_with_env"
        self.app_without_env = "app_without_env"
        Path(
            str(Path(self.base_dir) / "roles" / self.app_with_env / "templates")
        ).mkdir(parents=True, exist_ok=True)
        Path(
            str(Path(self.base_dir) / "roles" / self.app_without_env / "templates")
        ).mkdir(parents=True, exist_ok=True)

        with Path(
            str(
                Path(self.base_dir)
                / "roles"
                / self.app_with_env
                / "templates"
                / "env.j2"
            )
        ).open("w") as f:
            f.write("")

    def tearDown(self):
        if Path(self.base_dir).exists():
            shutil.rmtree(self.base_dir)

    def test_env_exists(self):
        """Test that has_env returns True if env.j2 exists."""
        self.assertTrue(has_env(self.app_with_env, base_dir=self.base_dir))

    def test_env_not_exists(self):
        """Test that has_env returns False if env.j2 does not exist."""
        self.assertFalse(has_env(self.app_without_env, base_dir=self.base_dir))


if __name__ == "__main__":
    unittest.main()
