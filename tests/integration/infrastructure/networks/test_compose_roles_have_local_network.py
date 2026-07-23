"""Per: every role that ships a Compose template MUST declare its
own local subnet under ``meta/networks.yml.local.subnet``."""

from __future__ import annotations

import unittest

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_META_NETWORKS,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)


class TestComposeRolesHaveLocalNetwork(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from . import PROJECT_ROOT

        cls.repo_root = str(PROJECT_ROOT)
        cls.roles_dir = PROJECT_ROOT / "roles"

    def test_every_compose_role_with_application_id_has_local_network(self):
        missing = []

        for role_path in sorted(self.roles_dir.iterdir()):
            if not role_path.is_dir():
                continue

            role_name = role_path.name
            compose_template = role_path / ROLE_FILE_TEMPL_COMPOSE
            if not compose_template.is_file():
                continue

            vars_file = role_path / ROLE_FILE_VARS_MAIN
            if not vars_file.is_file():
                continue

            vars_data = load_yaml_any(str(vars_file)) or {}
            application_id = vars_data.get("application_id")
            if not application_id:
                continue

            networks_file = role_path / ROLE_FILE_META_NETWORKS
            subnet = None
            if networks_file.is_file():
                networks = load_yaml_any(str(networks_file)) or {}
                local = networks.get("local") if isinstance(networks, dict) else None
                if isinstance(local, dict):
                    subnet = local.get("subnet")

            if not subnet:
                missing.append((role_name, application_id))

        if missing:
            details = "\n".join(
                f"  - role '{role}' (application_id='{app_id}')"
                for role, app_id in missing
            )
            self.fail(
                "The following roles ship a templates/compose.yml.j2 and define "
                "an application_id but have no local.subnet entry in "
                "meta/networks.yml:\n" + details
            )


if __name__ == "__main__":
    unittest.main()
