import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from utils.cache.yaml import dump_yaml_str
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_USERS,
    ROLE_FILE_META_VARIANTS,
)

from . import PROJECT_ROOT

SCRIPT_PATH = str(
    (
        PROJECT_ROOT
        / "cli"
        / "administration"
        / "inventory"
        / "validate"
        / "__main__.py"
    ).resolve()
)


class TestValidateInventory(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.roles_dir = Path(self.temp_dir) / "roles"
        (self.roles_dir / "app1" / "meta").mkdir(parents=True)
        (self.roles_dir / "identity" / "meta").mkdir(parents=True)
        self.inventory_dir = Path(self.temp_dir) / "inventory"
        self.inventory_dir.mkdir()

        (self.roles_dir / "app1" / ROLE_FILE_META_SERVICES).write_text(
            dump_yaml_str(
                {"port": 8080, "enabled": True, "settings": {"theme": "dark"}}
            ),
            encoding="utf-8",
        )
        # Per the file root IS the users map (no `users:` wrapper).
        (self.roles_dir / "identity" / ROLE_FILE_META_USERS).write_text(
            dump_yaml_str({"alice": {"email": "alice@example.com"}}),
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def run_script(self, expected_code=0):
        result = subprocess.run(
            [
                sys.executable,
                SCRIPT_PATH,
                str(self.inventory_dir),
                "--roles-dir",
                str(self.roles_dir),
            ],
            capture_output=True,
            encoding="utf-8",
            cwd=self.temp_dir,
            check=False,
        )
        if result.returncode != expected_code:
            print("STDOUT:", result.stdout)
            print("STDERR:", result.stderr)
        return result

    def test_valid_inventory(self):
        # Per, application defaults derived from meta/services.yml
        # surface under `applications.<id>.services.<entity>` (the file root
        # is the services map keyed by entity name). The flat keys
        # port/enabled/settings the fixture writes into meta/services.yml
        # therefore appear as services entries in the defaults dict, and
        # the inventory side must mirror that shape.
        (self.inventory_dir / "group_vars.yml").write_text(
            dump_yaml_str(
                {
                    "applications": {
                        "app1": {
                            "services": {
                                "port": 8080,
                                "enabled": True,
                                "settings": {"theme": "dark"},
                            }
                        }
                    },
                    "users": {
                        "alice": {
                            "email": "alice@example.com",
                            "password": "secret",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        result = self.run_script(expected_code=0)
        self.assertIn("Inventory directory is valid against defaults", result.stdout)

    def test_unknown_user_warning(self):
        (self.inventory_dir / "invalid_users.yml").write_text(
            dump_yaml_str({"users": {"bob": {"email": "bob@example.com"}}}),
            encoding="utf-8",
        )

        result = self.run_script(expected_code=0)
        self.assertIn("Warning", result.stderr)

    def test_missing_user_key_fails(self):
        (self.inventory_dir / "invalid_key.yml").write_text(
            dump_yaml_str(
                {
                    "users": {
                        "alice": {
                            "email": "alice@example.com",
                            "extra": "unexpected",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        result = self.run_script(expected_code=1)
        self.assertIn("Missing default for user 'alice': key 'extra'", result.stderr)

    def test_missing_application_key_fails(self):
        (self.inventory_dir / "missing_key.yml").write_text(
            dump_yaml_str(
                {
                    "applications": {
                        "app1": {
                            "services": {
                                "port": 8080,
                                "enabled": True,
                                "settings": {"theme": "dark"},
                                "extra_setting": True,
                            }
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        result = self.run_script(expected_code=1)
        self.assertIn("Missing default for app1: services.extra_setting", result.stdout)

    def test_variants_only_key_is_accepted(self):
        """Regression for web-opt-rdr-www failure on run 26428083128:
        variants.yml declares service-keys absent from meta/services.yml,
        the matrix-deploy bake floats those keys into host_vars, and the
        validator must treat them as legal because variants.yml is part
        of the role contract."""
        (self.roles_dir / "app1" / ROLE_FILE_META_VARIANTS).write_text(
            dump_yaml_str(
                [
                    {"services": {"dashboard": {"enabled": True, "shared": True}}},
                    {"services": {"dashboard": {"enabled": False, "shared": False}}},
                ]
            ),
            encoding="utf-8",
        )

        (self.inventory_dir / "variants_only.yml").write_text(
            dump_yaml_str(
                {
                    "applications": {
                        "app1": {
                            "services": {
                                "port": 8080,
                                "enabled": True,
                                "settings": {"theme": "dark"},
                                "dashboard": {"enabled": True, "shared": True},
                            }
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        result = self.run_script(expected_code=0)
        self.assertNotIn("Missing default", result.stdout)


if __name__ == "__main__":
    unittest.main()
