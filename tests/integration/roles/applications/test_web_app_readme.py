import unittest

from utils.cache import PROJECT_ROOT, ROLES_DIR


def web_app_role_dirs() -> list:
    """Return all role directories that match roles/web-app-*."""
    return sorted([p for p in ROLES_DIR.glob("web-app-*") if p.is_dir()])


class TestWebAppRolesHaveReadme(unittest.TestCase):
    """
    Ensures every role under roles/web-app-* contains a README.md.

    Why: The README is required for the role to be shown in the Web App Dashboard.
    """

    @classmethod
    def setUpClass(cls):
        cls.repo_root = PROJECT_ROOT
        cls.roles = web_app_role_dirs()

    def test_roles_directory_present(self):
        self.assertTrue(
            (self.repo_root / "roles").is_dir(),
            f"'roles' directory not found at: {self.repo_root}",
        )

    def test_every_web_app_role_has_readme(self):
        missing = []
        for role_dir in self.roles:
            with self.subTest(role=role_dir.name):
                readme = role_dir / "README.md"
                if not readme.is_file():
                    missing.append(role_dir)

        if missing:
            formatted = "\n".join(f"- {p.relative_to(self.repo_root)}" for p in missing)
            self.fail(
                "The following roles are missing a README.md:\n"
                f"{formatted}\n\n"
                "A README.md is required so the role can be displayed in the Web App Dashboard."
            )


if __name__ == "__main__":
    unittest.main()
