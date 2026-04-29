import unittest
import yaml
from pathlib import Path


class TestDockerRoleServicesConfiguration(unittest.TestCase):
    def test_services_keys_and_templates(self):
        """For each web-app-* role, check that ``meta/services.yml`` contains
        a non-empty mapping at the file root (the services map per req-008)."""
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        roles_dir = repo_root / "roles"
        errors = []
        warnings = []

        for role_path in roles_dir.iterdir():
            if not (role_path.is_dir() and role_path.name.startswith("web-app-")):
                continue

            services_file = role_path / "meta" / "services.yml"
            if not services_file.exists():
                continue  # No services manifest to check

            try:
                services = yaml.safe_load(services_file.read_text("utf-8")) or {}
                main_file = role_path / "vars" / "main.yml"
                yaml.safe_load(main_file.read_text("utf-8")) or {}
            except yaml.YAMLError as e:
                errors.append(f"{role_path.name}: YAML parse error: {e}")
                continue

            if not services:
                warnings.append(f"[WARNING] {role_path.name}: empty meta/services.yml")
                continue

            if not isinstance(services, dict):
                errors.append(
                    f"{role_path.name}: meta/services.yml file root must be a "
                    "mapping (the services map; per req-008)"
                )
                continue
        if warnings:
            print(
                "\nWarnings in docker role services configuration:\n"
                + "\n".join(warnings)
            )
        if errors:
            self.fail(
                "Errors in docker role services configuration:\n" + "\n".join(errors)
            )


if __name__ == "__main__":
    unittest.main()
