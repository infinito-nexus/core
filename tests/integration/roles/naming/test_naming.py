import re
import unittest

from . import PROJECT_ROOT

ROLE_NAME_PATTERN = re.compile(r"^[a-z0-9-]+(?:_[a-z0-9-]+)?$")


class TestRoleNames(unittest.TestCase):
    def test_role_names_follow_naming_convention(self):
        roles_dir = PROJECT_ROOT / "roles"
        self.assertTrue(
            roles_dir.is_dir(), f"'roles/' directory not found at {roles_dir}"
        )

        invalid_names = []

        for role_path in roles_dir.iterdir():
            if not role_path.is_dir():
                continue

            name = role_path.name

            if name.startswith(".") or name == "__pycache__":
                continue

            if not ROLE_NAME_PATTERN.fullmatch(name):
                invalid_names.append(name)

        self.assertFalse(
            invalid_names,
            "The following role directory names violate the naming convention "
            "(only a–z, 0–9, '-', max one '_', and '_' must be followed by at least one character):\n"
            + "\n".join(f"- {n}" for n in invalid_names),
        )


if __name__ == "__main__":
    unittest.main()
