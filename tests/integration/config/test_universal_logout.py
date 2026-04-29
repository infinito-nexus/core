import unittest
import glob
import yaml


class TestUniversalLogoutSetting(unittest.TestCase):
    ROLES_PATH = "roles/web-app-*/meta/services.yml"

    def test_logout_defined(self):
        files = glob.glob(self.ROLES_PATH)
        self.assertGreater(
            len(files), 0, f"No role config files found under {self.ROLES_PATH}"
        )

        errors = []

        for file_path in files:
            with open(file_path, "r", encoding="utf-8") as f:
                try:
                    data = yaml.safe_load(f)
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
                if not isinstance(val, bool):
                    errors.append(
                        f"The 'services.logout.enabled' setting in '{file_path}' must be boolean true or false, "
                        f"but found: {val} (type {type(val).__name__})"
                    )

        if errors:
            self.fail("\n\n".join(errors))


if __name__ == "__main__":
    unittest.main()
