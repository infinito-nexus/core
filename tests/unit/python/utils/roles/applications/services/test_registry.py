from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, iter_project_files
from utils.cache.yaml import dump_yaml_str, load_yaml_any
from utils.roles.applications.services.registry import (
    GATED_LOOKUPS,
    GROUP_GATED_CONSTANTS,
    ServiceRegistryError,
    build_service_registry_from_applications,
    build_service_registry_from_roles_dir,
    detect_service_bucket,
    detect_service_channel,
    expand_service_tokens,
    is_explicit_truth,
    ordered_primary_service_entries,
    resolve_service_dependency_roles_from_config,
)
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN


class TestServiceRegistryDiscovery(unittest.TestCase):
    """Per, the materialised application payload exposes services
    under the bare ``services`` key (no ``compose.services`` wrapper)."""

    def test_discovery_reads_provides_canonical_shared_and_enabled(self):
        applications = {
            "web-app-keycloak": {
                "services": {
                    "keycloak": {
                        "enabled": False,
                        "shared": True,
                        "provides": "oidc",
                    }
                }
            },
            "web-svc-cdn": {
                "services": {
                    "cdn": {"enabled": False, "shared": True},
                    "css": {"enabled": True, "shared": True, "canonical": "cdn"},
                    "javascript": {
                        "enabled": False,
                        "shared": True,
                        "canonical": "cdn",
                    },
                }
            },
        }

        registry = build_service_registry_from_applications(applications)

        self.assertEqual(registry["oidc"]["role"], "web-app-keycloak")
        self.assertEqual(registry["oidc"]["entity_name"], "keycloak")
        self.assertTrue(registry["oidc"]["shared"])
        self.assertFalse(registry["oidc"]["enabled"])

        self.assertEqual(registry["cdn"]["role"], "web-svc-cdn")
        self.assertNotIn("canonical", registry["cdn"])
        self.assertEqual(registry["css"]["canonical"], "cdn")
        self.assertTrue(registry["css"]["enabled"])
        self.assertTrue(registry["javascript"]["shared"])

    def test_entity_name_derivation_for_relevant_role_prefixes(self):
        applications = {
            "web-app-dashboard": {
                "services": {"dashboard": {"enabled": False, "shared": True}}
            },
            "web-svc-file": {"services": {"file": {"enabled": False, "shared": True}}},
            "svc-db-mariadb": {
                "services": {"mariadb": {"enabled": False, "shared": True}}
            },
            "svc-ai-ollama": {
                "services": {"ollama": {"enabled": False, "shared": True}}
            },
        }

        registry = build_service_registry_from_applications(applications)

        self.assertIn("dashboard", registry)
        self.assertIn("file", registry)
        self.assertIn("mariadb", registry)
        self.assertIn("ollama", registry)
        self.assertEqual(detect_service_channel("web-app-dashboard"), "frontend")
        self.assertEqual(detect_service_channel("svc-db-mariadb"), "backend")
        self.assertEqual(detect_service_bucket("web-app-dashboard"), "web-app")
        self.assertEqual(detect_service_bucket("web-svc-file"), "web-svc")
        self.assertEqual(detect_service_bucket("svc-db-mariadb"), "universal")

    def test_discovery_passes_overlay_block_through(self):
        applications = {
            "svc-db-mariadb": {
                "services": {"mariadb": {"enabled": True, "shared": True}},
                "networks": {
                    "overlay": {
                        "modes": ["compose", "swarm"],
                        "topology": "shared_net",
                        "aliases": ["mariadb"],
                        "consumer": {"kind": "database"},
                    }
                },
            },
            "svc-prx-openresty": {
                "services": {"openresty": {"enabled": True, "shared": True}},
                "networks": {
                    "overlay": {
                        "modes": ["swarm"],
                        "topology": "default_net",
                        "aliases": [],
                        "consumer": {
                            "kind": "services_flags",
                            "key": "sso",
                            "flags": ["enabled"],
                        },
                    }
                },
            },
            "web-app-keycloak": {
                "services": {
                    "keycloak": {
                        "enabled": True,
                        "shared": True,
                        "provides": "oidc",
                    }
                },
                "networks": {
                    "overlay": {
                        "modes": ["swarm"],
                        "proxy_resolvable": True,
                        "aliases": ["auth.example"],
                    }
                },
            },
            "web-app-plain": {"services": {"plain": {"enabled": True, "shared": True}}},
        }

        registry = build_service_registry_from_applications(applications)

        self.assertEqual(registry["mariadb"]["overlay"]["modes"], ["compose", "swarm"])
        self.assertEqual(registry["mariadb"]["overlay"]["topology"], "shared_net")
        self.assertEqual(registry["mariadb"]["overlay"]["consumer"]["kind"], "database")
        self.assertEqual(registry["openresty"]["overlay"]["modes"], ["swarm"])
        self.assertEqual(registry["openresty"]["overlay"]["aliases"], [])
        self.assertTrue(registry["oidc"]["overlay"]["proxy_resolvable"])
        self.assertNotIn("topology", registry["oidc"]["overlay"])
        self.assertEqual(registry["oidc"]["overlay"]["aliases"], ["auth.example"])
        self.assertNotIn("overlay", registry["plain"])

    def test_direct_service_resolution_uses_role_local_names(self):
        registry = {
            "ldap": {"role": "svc-db-openldap"},
            "mariadb": {"role": "svc-db-mariadb"},
        }
        config = {
            "services": {
                "ldap": {"enabled": True, "shared": True},
                "mariadb": {"enabled": True, "shared": True},
                "ignored": {"enabled": True, "shared": False},
            }
        }

        self.assertEqual(
            resolve_service_dependency_roles_from_config(config, registry),
            ["svc-db-openldap", "svc-db-mariadb"],
        )


class TestServiceRegistryOrdering(unittest.TestCase):
    """Per, ``run_after`` lives on the role's primary entity at
    ``meta/services.yml.<primary_entity>.run_after``."""

    def _mk_role(
        self,
        root: Path,
        role: str,
        primary_entity: str,
        services_payload: dict,
        *,
        run_after: list[str] | None = None,
    ) -> None:

        role_dir = root / role
        meta_dir = role_dir / "meta"
        meta_dir.mkdir(parents=True, exist_ok=True)

        services = dict(services_payload)
        if run_after is not None:
            primary = dict(services.get(primary_entity, {}) or {})
            if run_after:
                primary["run_after"] = list(run_after)
            services[primary_entity] = primary

        meta_dir.joinpath("services.yml").write_text(
            dump_yaml_str(services),
            encoding="utf-8",
        )
        meta_dir.joinpath("main.yml").write_text(
            "galaxy_info: {}\n",
            encoding="utf-8",
        )

    def test_ordered_entries_follow_bucket_order_and_run_after(self):
        registry = {
            "mariadb": {
                "role": "svc-db-mariadb",
                "bucket": "universal",
                "deploy_type": "universal",
            },
            "file": {
                "role": "web-svc-file",
                "bucket": "web-svc",
                "deploy_type": "server",
            },
            "asset": {
                "role": "web-svc-asset",
                "bucket": "web-svc",
                "deploy_type": "server",
            },
            "matomo": {
                "role": "web-app-matomo",
                "bucket": "web-app",
                "deploy_type": "server",
            },
            "dashboard": {
                "role": "web-app-dashboard",
                "bucket": "web-app",
                "deploy_type": "server",
            },
        }

        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td)
            self._mk_role(
                roles_dir,
                "svc-db-mariadb",
                "mariadb",
                {"mariadb": {"enabled": False, "shared": True}},
            )
            self._mk_role(
                roles_dir,
                "web-svc-file",
                "file",
                {"file": {"enabled": False, "shared": True}},
            )
            self._mk_role(
                roles_dir,
                "web-svc-asset",
                "asset",
                {"asset": {"enabled": False, "shared": True}},
                run_after=["web-svc-file"],
            )
            self._mk_role(
                roles_dir,
                "web-app-matomo",
                "matomo",
                {"matomo": {"enabled": False, "shared": True}},
            )
            self._mk_role(
                roles_dir,
                "web-app-dashboard",
                "dashboard",
                {"dashboard": {"enabled": False, "shared": True}},
                run_after=["web-app-matomo"],
            )

            ordered = ordered_primary_service_entries(registry, roles_dir)

        self.assertEqual(
            [entry["role"] for entry in ordered],
            [
                "svc-db-mariadb",
                "web-svc-file",
                "web-svc-asset",
                "web-app-matomo",
                "web-app-dashboard",
            ],
        )

    def test_run_after_orders_across_buckets(self):
        registry = {
            "file": {
                "role": "web-svc-file",
                "bucket": "web-svc",
                "deploy_type": "server",
            },
            "mail": {
                "role": "sys-svc-mail",
                "bucket": "universal",
                "deploy_type": "universal",
            },
        }

        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td)
            self._mk_role(
                roles_dir,
                "web-svc-file",
                "file",
                {"file": {"enabled": False, "shared": True}},
                run_after=["sys-svc-mail"],
            )
            self._mk_role(
                roles_dir,
                "sys-svc-mail",
                "mail",
                {"mail": {"enabled": False, "shared": True}},
            )

            ordered = ordered_primary_service_entries(registry, roles_dir)

        self.assertEqual(
            [entry["role"] for entry in ordered],
            ["sys-svc-mail", "web-svc-file"],
        )

    def test_circular_run_after_fails_hard(self):
        registry = {
            "file": {"role": "web-svc-file", "bucket": "web-svc"},
            "asset": {"role": "web-svc-asset", "bucket": "web-svc"},
        }

        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td)
            self._mk_role(
                roles_dir,
                "web-svc-file",
                "file",
                {"file": {"enabled": False, "shared": True}},
                run_after=["web-svc-asset"],
            )
            self._mk_role(
                roles_dir,
                "web-svc-asset",
                "asset",
                {"asset": {"enabled": False, "shared": True}},
                run_after=["web-svc-file"],
            )

            with self.assertRaises(ServiceRegistryError):
                ordered_primary_service_entries(registry, roles_dir)


class TestDispatcherExpansion(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.roles_dir = Path(self._tmp.name) / "roles"
        self._role(
            "web-app-email", {"email": {"shared": True, "provider": "web-app-mx"}}
        )
        self._role("web-app-mx", {"mx": {"shared": True, "covers": ["email"]}})
        self._role("web-app-other", {"other": {"shared": True}})

    def _role(self, role: str, services: dict) -> None:
        services_file = self.roles_dir / role / ROLE_FILE_META_SERVICES
        vars_file = self.roles_dir / role / ROLE_FILE_VARS_MAIN
        services_file.parent.mkdir(parents=True)
        vars_file.parent.mkdir(parents=True)
        services_file.write_text(dump_yaml_str(services), encoding="utf-8")
        vars_file.write_text(f"application_id: {role}\n", encoding="utf-8")

    def test_disabling_the_selected_provider_disables_the_dispatcher(self):
        self.assertEqual(
            ["mx", "email"], expand_service_tokens(["web-app-mx"], self.roles_dir)
        )

    def test_the_provider_service_key_disables_the_dispatcher_too(self):
        self.assertEqual(["mx", "email"], expand_service_tokens(["mx"], self.roles_dir))

    def test_disabling_the_dispatcher_leaves_its_provider(self):
        self.assertEqual(
            ["email"], expand_service_tokens(["web-app-email"], self.roles_dir)
        )

    def test_an_unrelated_role_disables_no_dispatcher(self):
        self.assertEqual(
            ["other", "unknown"],
            expand_service_tokens(["web-app-other", "unknown"], self.roles_dir),
        )

    def test_the_registry_records_the_selected_provider(self):
        registry = build_service_registry_from_roles_dir(self.roles_dir)
        self.assertEqual("web-app-mx", registry["email"]["provider"])
        self.assertNotIn("provider", registry["mx"])


class TestExplicitTruth(unittest.TestCase):
    """A flag may resolve a dependency through a group-gated constant.

    The substring rule reads the role id out of the flag itself, so a SPOT
    constant hides it. Roles referencing one keep their provider only while
    the constant is registered.
    """

    def test_a_literal_true_resolves(self):
        self.assertTrue(is_explicit_truth(True))

    def test_the_in_group_names_form_resolves(self):
        self.assertTrue(is_explicit_truth("{{ 'web-app-keycloak' in group_names }}"))

    def test_every_registered_constant_resolves(self):
        for constant in GROUP_GATED_CONSTANTS:
            with self.subTest(constant=constant):
                self.assertTrue(is_explicit_truth("{{ " + constant + " }}"))

    def test_every_registered_lookup_resolves(self):
        for token in GATED_LOOKUPS:
            with self.subTest(token=token):
                self.assertTrue(is_explicit_truth("{{ " + token + ", 'clearnet') }}"))

    def test_every_registered_lookup_has_a_plugin(self):
        for token in GATED_LOOKUPS:
            name = token.split("'")[1]
            with self.subTest(lookup=name):
                self.assertTrue(
                    (PROJECT_ROOT / "plugins" / "lookup" / f"{name}.py").is_file()
                )

    def test_an_unregistered_jinja_expression_does_not_resolve(self):
        self.assertFalse(
            is_explicit_truth("{{ lookup('config', 'web-app-gitea', 'mcp.enabled') }}")
        )

    def test_a_literal_false_does_not_resolve(self):
        self.assertFalse(is_explicit_truth(False))

    def test_every_registered_constant_is_defined_in_group_vars(self):
        group_vars = PROJECT_ROOT / "group_vars" / "all"
        defined = {
            key
            for path in iter_project_files(extensions=(".yml",))
            if Path(path).parent == group_vars
            for key in load_yaml_any(path)
        }
        for constant in GROUP_GATED_CONSTANTS:
            with self.subTest(constant=constant):
                self.assertIn(constant, defined)


if __name__ == "__main__":
    unittest.main()
