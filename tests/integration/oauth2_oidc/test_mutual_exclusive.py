import unittest
from pathlib import Path

import yaml


ROLES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "roles"


class TestOidcOauth2MutualExclusion(unittest.TestCase):
    def test_oidc_and_oauth2_are_not_enabled_at_the_same_time(self):
        failures = []

        for role_path in sorted(ROLES_DIR.iterdir()):
            config_file = role_path / "meta" / "services.yml"
            if not config_file.exists():
                continue

            try:
                with config_file.open("r", encoding="utf-8") as handle:
                    data = yaml.safe_load(handle) or {}
            except yaml.YAMLError as error:
                failures.append(f"{config_file}: failed to parse YAML ({error})")
                continue

            # Per req-008 the file root of meta/services.yml IS the
            # services map (no `compose.services` wrapper).
            services = data if isinstance(data, dict) else {}
            oidc_enabled = services.get("oidc", {}).get("enabled") is True
            oauth2_enabled = services.get("oauth2", {}).get("enabled") is True

            if oidc_enabled and oauth2_enabled:
                failures.append(
                    f"{config_file}: services.oidc.enabled and "
                    "services.oauth2.enabled are both true. "
                    "Enable only one of them, because using both at the same time is redundant."
                )

        if failures:
            self.fail(
                "OIDC and OAuth2 must not be enabled at the same time in role configs. "
                "Enable only one of them, because using both is redundant.\n\n"
                + "\n".join(failures)
            )


if __name__ == "__main__":
    unittest.main()
