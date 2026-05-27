import glob
import unittest

import yaml

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES


class TestUniversalLogoutSetting(unittest.TestCase):
    ROLES_PATH = f"roles/web-app-*/{ROLE_FILE_META_SERVICES}"

    def test_logout_defined(self):
        files = glob.glob(self.ROLES_PATH)  # nocheck: project-walk
        self.assertGreater(
            len(files), 0, f"No role config files found under {self.ROLES_PATH}"
        )

        errors = []

        for file_path in files:
            try:
                data = load_yaml_any(file_path)
            except yaml.YAMLError as e:
                errors.append(f"YAML parse error in '{file_path}': {e}")
                continue

            services = data if isinstance(data, dict) else {}
            logout = services.get("logout", {}) or {}

            if "enabled" not in logout:
                errors.append(
                    f"Missing 'services.logout.enabled' setting in '{file_path}'. "
                    "You must explicitly set it to true or false for this app."
                )
            else:
                val = logout["enabled"]
                is_dynamic = isinstance(val, str) and "in group_names" in val
                if not isinstance(val, bool) and not is_dynamic:
                    errors.append(
                        f"The 'services.logout.enabled' setting in '{file_path}' must be boolean true/false "
                        f"or a Jinja `\"{{{{ '<role>' in group_names }}}}\"` expression, "
                        f"but found: {val} (type {type(val).__name__})"
                    )

        if errors:
            self.fail("\n\n".join(errors))


if __name__ == "__main__":
    unittest.main()
