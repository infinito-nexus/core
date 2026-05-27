import os
import unittest
from pathlib import Path

from utils.roles.mapping import ROLE_FILE_META_MAIN

ROLES_DIR = str(
    Path(str(Path(str(Path(__file__).parent)) / "../../../../roles")).resolve()
)


class TestRolesHaveMetaMain(unittest.TestCase):
    def test_each_role_has_meta_main(self):
        missing_meta = []

        for role in os.listdir(ROLES_DIR):
            # Ignore Python cache and hidden directories
            if role.startswith(".") or role == "__pycache__":
                continue

            role_path = str(Path(ROLES_DIR) / role)
            if not Path(role_path).is_dir():
                continue

            meta_main = str(Path(role_path) / ROLE_FILE_META_MAIN)
            if not Path(meta_main).is_file():
                missing_meta.append(role)

        if missing_meta:
            self.fail(
                "The following roles are missing meta/main.yml:\n"
                + "\n".join(missing_meta)
            )


if __name__ == "__main__":
    unittest.main()
