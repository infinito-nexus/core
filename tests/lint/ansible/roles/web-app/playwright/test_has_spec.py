import unittest

from utils.roles.mapping import ROLE_FILE_PLAYWRIGHT_SPEC

from . import PROJECT_ROOT


class TestWebAppRolesHavePlaywrightSpec(unittest.TestCase):
    def test_web_app_roles_have_playwright_spec(self):
        """
        Every roles/web-app-* role MUST ship a Playwright spec at
        ``ROLE_FILE_PLAYWRIGHT_SPEC``. A missing spec is a hard error so
        the meta/services.yml registry and the per-role auth + persona
        contract are never silently absent from the deploy capstone.
        """
        root = PROJECT_ROOT
        roles_dir = root / "roles"
        self.assertTrue(
            roles_dir.is_dir(), f"'roles' directory not found at: {roles_dir}"
        )

        missing: list[str] = []
        for role_path in sorted(roles_dir.iterdir()):
            if not (role_path.is_dir() and role_path.name.startswith("web-app-")):
                continue

            spec_file = role_path / ROLE_FILE_PLAYWRIGHT_SPEC
            if not spec_file.is_file():
                missing.append(role_path.name)

        if missing:
            self.fail(
                f"Missing {ROLE_FILE_PLAYWRIGHT_SPEC} in:\n  - "
                + "\n  - ".join(missing)
            )


if __name__ == "__main__":
    unittest.main()
