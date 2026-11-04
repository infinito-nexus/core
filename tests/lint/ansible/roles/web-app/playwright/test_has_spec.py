import unittest

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_META_MAIN, ROLE_FILE_PLAYWRIGHT_SPEC

from . import PROJECT_ROOT

_RULE = "playwright-spec"


def _opted_out(role_path) -> bool:
    meta_main = role_path / ROLE_FILE_META_MAIN
    if not meta_main.is_file():
        return False
    return is_suppressed_in_head(read_text(str(meta_main)).splitlines(), _RULE)


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
            if not spec_file.is_file() and not _opted_out(role_path):
                missing.append(role_path.name)

        if missing:
            self.fail(
                f"Missing {ROLE_FILE_PLAYWRIGHT_SPEC} in:\n  - "
                + "\n  - ".join(missing)
            )

    def test_an_opted_out_role_ships_no_spec(self):
        offenders = [
            role_path.name
            for role_path in sorted((PROJECT_ROOT / "roles").iterdir())
            if role_path.is_dir()
            and _opted_out(role_path)
            and (role_path / ROLE_FILE_PLAYWRIGHT_SPEC).is_file()
        ]
        self.assertEqual(
            [],
            offenders,
            f"'# nocheck: {_RULE}' in meta/main.yml next to a shipped spec:\n  - "
            + "\n  - ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
