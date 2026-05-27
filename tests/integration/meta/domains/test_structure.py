import unittest
from collections import Counter

import yaml

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"


class TestDomainsStructure(unittest.TestCase):
    def test_domains_keys_types_and_uniqueness(self):
        """Ensure that under 'domains' only 'canonical' and 'aliases' keys exist,
        'aliases' is a list of strings, 'canonical' is either a list of strings
        or a dict with string values, and no domain is defined more than once
        across all roles."""
        failed_roles = []
        all_domains = []

        for role_path in ROLES_DIR.iterdir():
            if not role_path.is_dir():
                continue
            vars_dir = role_path / "vars"
            if not vars_dir.exists():
                continue

            for vars_file in vars_dir.glob("*.yml"):
                try:
                    data = load_yaml_any(vars_file) or {}
                except yaml.YAMLError as e:
                    failed_roles.append(
                        (role_path.name, vars_file.name, f"YAML error: {e}")
                    )
                    continue

                if "domains" not in data:
                    continue

                domains = data.get("server", {}).get("domains")
                if not isinstance(domains, dict):
                    failed_roles.append(
                        (role_path.name, vars_file.name, "'domains' should be a dict")
                    )
                    continue

                # Check allowed keys
                allowed_keys = {"canonical", "aliases"}
                extra_keys = set(domains.keys()) - allowed_keys
                if extra_keys:
                    failed_roles.append(
                        (
                            role_path.name,
                            vars_file.name,
                            f"Unexpected keys in 'domains': {extra_keys}",
                        )
                    )

                # Validate and collect 'aliases'
                if "aliases" in domains:
                    aliases = domains["aliases"]
                    if not isinstance(aliases, list) or not all(
                        isinstance(item, str) for item in aliases
                    ):
                        failed_roles.append(
                            (
                                role_path.name,
                                vars_file.name,
                                "'aliases' must be a list of strings",
                            )
                        )
                    else:
                        all_domains.extend(aliases)

                # Validate and collect 'canonical'
                if "canonical" in domains:
                    canonical = domains["canonical"]
                    if isinstance(canonical, list):
                        if not all(isinstance(item, str) for item in canonical):
                            failed_roles.append(
                                (
                                    role_path.name,
                                    vars_file.name,
                                    "'canonical' list items must be strings",
                                )
                            )
                        else:
                            all_domains.extend(canonical)
                    elif isinstance(canonical, dict):
                        if not all(
                            isinstance(k, str) and isinstance(v, str)
                            for k, v in canonical.items()
                        ):
                            failed_roles.append(
                                (
                                    role_path.name,
                                    vars_file.name,
                                    "All keys and values in 'canonical' dict must be strings",
                                )
                            )
                        else:
                            all_domains.extend(canonical.values())
                    else:
                        failed_roles.append(
                            (
                                role_path.name,
                                vars_file.name,
                                "'canonical' must be a list or a dict",
                            )
                        )

        # Check for duplicate domains across all roles
        duplicates = [
            domain for domain, count in Counter(all_domains).items() if count > 1
        ]
        if duplicates:
            failed_roles.append(
                ("GLOBAL", "", f"Duplicate domain entries found: {duplicates}")
            )

        if failed_roles:
            messages = []
            for role, file, reason in failed_roles:
                entry = f"{role}/{file}: {reason}" if file else f"{role}: {reason}"
                messages.append(entry)
            self.fail("Domain structure errors found:\n" + "\n".join(messages))


if __name__ == "__main__":
    unittest.main()
