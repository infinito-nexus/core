import unittest

import yaml

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"


class TestOauth2AclMutualExclusion(unittest.TestCase):
    def test_acl_has_either_whitelist_or_blacklist(self):
        failures = []

        for role_path in ROLES_DIR.iterdir():
            vars_file = role_path / ROLE_FILE_META_SERVICES
            if not vars_file.exists():
                continue

            # open the YAML file instead of passing the Path object
            try:
                data = load_yaml_any(vars_file) or {}
            except yaml.YAMLError as e:
                failures.append(f"{role_path.name}: failed to parse YAML ({e})")
                continue

            services = data.get("services", {})
            oauth2 = services.get("oauth2", {})
            acl = oauth2.get("acl", None)
            if acl is None:
                continue

            has_wl = "whitelist" in acl
            has_bl = "blacklist" in acl

            if has_wl and has_bl:
                failures.append(
                    f"{role_path.name}: both 'whitelist' and 'blacklist' are defined"
                )

        if failures:
            self.fail(
                "The following roles define both whitelist and blacklist under services.oauth2.acl:\n"
                + "\n".join(failures)
            )


if __name__ == "__main__":
    unittest.main()
