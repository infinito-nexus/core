import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from ansible.errors import AnsibleError

domain_list = importlib.import_module("utils.domains.list")


class TestDomainList(unittest.TestCase):
    def write_role(self, roles_dir: Path, role_name: str, app_id: str, config: dict):
        # ``config`` is the legacy nested shape ``{"server": {"domains": {...}}}``
        # for readability; it gets unwrapped into the new file-root meta/server.yml.
        role_dir = roles_dir / role_name
        (role_dir / "vars").mkdir(parents=True, exist_ok=True)
        (role_dir / "meta").mkdir(parents=True, exist_ok=True)
        (role_dir / "vars" / "main.yml").write_text(
            yaml.safe_dump({"application_id": app_id}, sort_keys=False),
            encoding="utf-8",
        )
        server_payload = config.get("server", {}) if isinstance(config, dict) else {}
        (role_dir / "meta" / "server.yml").write_text(
            yaml.safe_dump(server_payload, sort_keys=False),
            encoding="utf-8",
        )

    def test_list_application_domains_renders_and_flattens_supported_shapes(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles_dir = Path(tmp) / "roles"
            roles_dir.mkdir()

            self.write_role(
                roles_dir,
                "web-app-dashboard",
                "web-app-dashboard",
                {
                    "server": {
                        "domains": {
                            "canonical": ["dashboard.{{ DOMAIN_PRIMARY }}"],
                            "aliases": ["www.dashboard.{{ DOMAIN_PRIMARY }}"],
                        }
                    }
                },
            )
            self.write_role(
                roles_dir,
                "web-app-minio",
                "web-app-minio",
                {
                    "server": {
                        "domains": {
                            "canonical": {
                                "api": "api.s3.{{ DOMAIN_PRIMARY }}",
                                "console": "console.s3.{{ DOMAIN_PRIMARY }}",
                            },
                            "aliases": [],
                        }
                    }
                },
            )

            with patch.object(domain_list, "ROLES_DIR", roles_dir):
                domains = domain_list.list_application_domains("infinito.example")

            self.assertEqual(
                domains,
                sorted(
                    [
                        "api.s3.infinito.example",
                        "console.s3.infinito.example",
                        "dashboard.infinito.example",
                        "test.infinito.example",
                    ]
                ),
            )

    def test_list_application_domains_can_include_aliases_and_www_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles_dir = Path(tmp) / "roles"
            roles_dir.mkdir()

            self.write_role(
                roles_dir,
                "web-app-dashboard",
                "web-app-dashboard",
                {
                    "server": {
                        "domains": {
                            "canonical": ["dashboard.{{ DOMAIN_PRIMARY }}"],
                            "aliases": ["www.dashboard.{{ DOMAIN_PRIMARY }}"],
                        }
                    }
                },
            )

            with patch.object(domain_list, "ROLES_DIR", roles_dir):
                domains = domain_list.list_application_domains(
                    "infinito.example",
                    include_aliases=True,
                    include_www=True,
                )

            self.assertEqual(
                domains,
                [
                    "dashboard.infinito.example",
                    "test.infinito.example",
                    "www.dashboard.infinito.example",
                    "www.test.infinito.example",
                ],
            )

    def test_list_application_domains_includes_derived_test_domain_without_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles_dir = Path(tmp) / "roles"
            roles_dir.mkdir()

            with patch.object(domain_list, "ROLES_DIR", roles_dir):
                domains = domain_list.list_application_domains("infinito.example")

            self.assertEqual(domains, ["test.infinito.example"])

    def test_list_application_domains_raises_on_collisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles_dir = Path(tmp) / "roles"
            roles_dir.mkdir()

            shared_config = {
                "server": {
                    "domains": {
                        "canonical": ["same.{{ DOMAIN_PRIMARY }}"],
                        "aliases": [],
                    }
                }
            }
            self.write_role(roles_dir, "app-a", "app-a", shared_config)
            self.write_role(roles_dir, "app-b", "app-b", shared_config)

            with patch.object(domain_list, "ROLES_DIR", roles_dir):
                with self.assertRaises(AnsibleError):
                    domain_list.list_application_domains("infinito.example")


if __name__ == "__main__":
    unittest.main()
