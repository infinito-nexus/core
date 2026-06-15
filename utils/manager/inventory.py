from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from utils.cache.applications import get_variants
from utils.handler.vault import VaultHandler, VaultScalar
from utils.handler.yaml import YamlHandler
from utils.manager.value_generator import ValueGenerator
from utils.roles.applications.services.database import has_single_database_service
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
    is_explicit_truth,
    resolve_service_dependency_roles_from_config,
)
from utils.roles.mapping import ROLE_FILE_META_SCHEMA, ROLE_FILE_VARS_MAIN

if TYPE_CHECKING:
    from pathlib import Path

# Marker fields that identify a credential schema leaf. Any
# `default:` value is preserved verbatim; algorithm defaults to `plain` when
# absent; `validation:` only applies to user-provided values.
_CREDENTIAL_LEAF_MARKERS = ("description", "algorithm", "validation", "default")


def _is_credential_leaf(node: Any) -> bool:
    return isinstance(node, dict) and any(
        marker in node for marker in _CREDENTIAL_LEAF_MARKERS
    )


def _meta_role_config(role_path: Path) -> dict[str, Any]:
    """Assemble the view of a role's config from its meta files.

    The shape mirrors the old `meta/services.yml` payload so that downstream
    helpers (database_service, service_registry, ...) keep working unchanged:
    `{services: <map>, server: <map>, rbac: <map>, volumes: <map>}`.
    """
    meta_dir = role_path / "meta"
    config: dict[str, Any] = {}
    for topic in ("services", "server", "rbac", "volumes"):
        topic_path = meta_dir / f"{topic}.yml"
        if not topic_path.exists():
            continue
        topic_data = YamlHandler.load_yaml(topic_path) or {}
        if isinstance(topic_data, dict) and topic_data:
            config[topic] = topic_data
    return config


class InventoryManager:
    def __init__(
        self,
        role_path: Path,
        inventory_path: Path,
        vault_pw: str,
        overrides: dict[str, str],
        allow_empty_plain: bool = False,
        variant: int | None = None,
    ):
        """Initialize the Inventory Manager."""
        self.role_path = role_path
        self.inventory_path = inventory_path
        self.vault_pw = vault_pw
        self.overrides = overrides
        self.allow_empty_plain = allow_empty_plain
        self.variant = variant

        self.inventory = YamlHandler.load_yaml(inventory_path) or {}
        self.schema = self._load_role_schema_by_path(role_path)
        self.app_id = self.load_application_id(role_path)

        self.vault_handler = VaultHandler(vault_pw)
        self.roles_root = self.role_path.parent
        self.value_generator = ValueGenerator()

    # ---------------------------------------------------------------------
    # File loading helpers
    # ---------------------------------------------------------------------

    def load_application_id(self, role_path: Path) -> str:
        """Load the application ID from the role's vars/main.yml file."""
        vars_file = role_path / ROLE_FILE_VARS_MAIN
        data = YamlHandler.load_yaml(vars_file) or {}
        app_id = data.get("application_id")
        if not app_id:
            print(f"ERROR: 'application_id' missing in {vars_file}", file=sys.stderr)
            sys.exit(1)
        return app_id

    @staticmethod
    def _load_role_schema_by_path(role_path: Path) -> dict[str, Any]:
        schema_path = role_path / ROLE_FILE_META_SCHEMA
        if not schema_path.exists():
            return {}
        return YamlHandler.load_yaml(schema_path) or {}

    def load_role_schema(self, role_name: str) -> dict[str, Any]:
        return self._load_role_schema_by_path(self.roles_root / role_name)

    def load_role_config_by_path(self, role_path: Path) -> dict[str, Any]:
        if role_path == self.role_path and self.variant is not None:
            variants = get_variants(roles_dir=str(self.roles_root))
            app_variants = variants.get(self.app_id) or [{}]
            if 0 <= self.variant < len(app_variants):
                return app_variants[self.variant] or {}
        return _meta_role_config(role_path)

    def load_role_config(self, role_name: str) -> dict[str, Any]:
        role_path = self.roles_root / role_name
        return self.load_role_config_by_path(role_path)

    # ---------------------------------------------------------------------
    # Shared provider resolution (recursive / transitive)
    # ---------------------------------------------------------------------

    def _direct_schema_includes_from_config(self, config: dict) -> list[str]:
        """
        Extract shared-provider dependencies from a single role config.
        """
        service_registry = build_service_registry_from_roles_dir(self.roles_root)
        return resolve_service_dependency_roles_from_config(config, service_registry)

    def resolve_schema_includes_recursive(self, root_role_name: str) -> list[str]:
        """
        Recursively resolve schema includes by following configs transitively.
        """
        resolved: list[str] = []
        seen: set[str] = set()

        # seed with root role's direct includes
        root_cfg = self.load_role_config_by_path(self.role_path)
        queue: list[str] = self._direct_schema_includes_from_config(root_cfg)

        while queue:
            role_name = queue.pop(0)
            if role_name in seen:
                continue
            seen.add(role_name)
            resolved.append(role_name)

            cfg = self.load_role_config(role_name)
            queue.extend(
                inc
                for inc in self._direct_schema_includes_from_config(cfg)
                if inc not in seen
            )

        return resolved

    # ---------------------------------------------------------------------
    # Schema application
    # ---------------------------------------------------------------------

    def _apply_one_role_schema(self, role_name: str) -> None:
        """
        Apply schema for a specific role into its application block.
        """
        role_path = self.roles_root / role_name
        app_id = self.load_application_id(role_path)
        schema = self.load_role_schema(role_name)
        if not schema:
            return

        apps = self.inventory.setdefault("applications", {})
        target = apps.setdefault(app_id, {})

        self.recurse_credentials(schema, target)

    def _apply_one_role_special_rules(self, role_path: Path) -> None:
        """
        Apply special credential rules based on role config flags.
        """
        app_id = self.load_application_id(role_path)
        cfg = self.load_role_config_by_path(role_path)

        services = cfg.get("services") or {}
        sso = services.get("sso") if isinstance(services, dict) else None
        sso = sso if isinstance(sso, dict) else {}
        if has_single_database_service({app_id: cfg}, app_id):
            apps = self.inventory.setdefault("applications", {})
            target = apps.setdefault(app_id, {})
            target.setdefault("credentials", {})["database_password"] = (
                self.value_generator.generate_value("alphanumeric")
            )

        # The oauth2-proxy sidecar (flavor: oauth2) needs a cookie secret
        # per consumer. Pure-OIDC roles do not, but the original branch
        # provisioned it for either flavor — keep that behaviour by
        # provisioning whenever services.sso.enabled is truthy.
        if is_explicit_truth(sso.get("enabled")):
            apps = self.inventory.setdefault("applications", {})
            target = apps.setdefault(app_id, {})
            target.setdefault("credentials", {})["sso_proxy_cookie_secret"] = (
                self.value_generator.generate_value("random_hex_16")
            )

        objstore_enabled = False
        if isinstance(services, dict):
            for engine in ("seaweedfs", "minio"):
                engine_cfg = services.get(engine)
                if isinstance(engine_cfg, dict) and is_explicit_truth(
                    engine_cfg.get("enabled")
                ):
                    objstore_enabled = True
                    break
        if objstore_enabled:
            apps = self.inventory.setdefault("applications", {})
            target = apps.setdefault(app_id, {})
            target.setdefault("credentials", {})["objstore_secret_key"] = (
                self.value_generator.generate_value("alphanumeric")
            )

    def apply_schema(self) -> dict:
        """
        Apply schema into inventory for:
          1) all recursively discovered shared-provider roles
          2) this role itself
        """
        # 1) Provider roles (transitive)
        for role_name in self.resolve_schema_includes_recursive(self.role_path.name):
            role_path = self.roles_root / role_name
            self._apply_one_role_special_rules(role_path)
            self._apply_one_role_schema(role_name)

        # 2) Root role
        self._apply_one_role_special_rules(self.role_path)

        apps = self.inventory.setdefault("applications", {})
        target = apps.setdefault(self.app_id, {})
        self.recurse_credentials(self.schema, target)

        return self.inventory

    # ---------------------------------------------------------------------
    # Credential recursion
    # ---------------------------------------------------------------------

    def recurse_credentials(self, branch: dict, dest: dict, prefix: str = "") -> None:
        """Recursively process the 'credentials' section and generate values.

        Supports the schema:
          * Nested keys are walked transparently (e.g.
            `credentials.recaptcha.{key,secret}`).
          * `algorithm:` defaults to `plain` when omitted.
          * `default:` (Jinja literal) is written verbatim and
            short-circuits algorithm-based generation. `validation:` is
            ignored for default-bearing entries.
          * Existing inventory values are preserved (no double-encryption,
            no overwrite of operator-supplied secrets).
        """
        for key, meta in (branch or {}).items():
            full_key = f"{prefix}.{key}" if prefix else key
            inside_credentials = prefix == "credentials" or prefix.startswith(
                "credentials."
            )

            if inside_credentials and _is_credential_leaf(meta):
                self._materialize_credential_leaf(full_key, key, meta, dest)
                continue

            if isinstance(meta, dict):
                sub = dest.setdefault(key, {})
                if not isinstance(sub, dict):
                    # Replace non-dict placeholder so nested credentials
                    # have a writeable container.
                    sub = {}
                    dest[key] = sub
                self.recurse_credentials(meta, sub, full_key)
            else:
                dest[key] = meta

    def _materialize_credential_leaf(
        self, full_key: str, key: str, meta: dict, dest: dict
    ) -> None:
        """Resolve a single credential leaf into ``dest[key]``."""
        existing_value = dest.get(key)

        if isinstance(existing_value, dict):
            print(
                f"Skipping encryption for '{key}', as it is a dictionary.",
                file=sys.stderr,
            )
            return

        if existing_value and isinstance(existing_value, VaultScalar):
            print(
                f"Skipping encryption for '{key}', as it is already vaulted.",
                file=sys.stderr,
            )
            return

        if "default" in meta:
            # Write the literal Jinja string verbatim, no rendering,
            # no validation, no algorithm-based generation.
            if isinstance(existing_value, str) and existing_value != "":
                return
            dest[key] = meta["default"]
            return

        algorithm = meta.get("algorithm") or "plain"

        if algorithm == "plain":
            if full_key in self.overrides:
                plain = self.overrides[full_key]
            elif isinstance(existing_value, str) and existing_value != "":
                return
            elif self.allow_empty_plain:
                plain = ""
            else:
                print(
                    f"ERROR: Plain algorithm for '{full_key}' requires override "
                    f"via --set {full_key}=<value>",
                    file=sys.stderr,
                )
                sys.exit(1)
        else:
            plain = self.overrides.get(
                full_key, self.value_generator.generate_value(algorithm)
            )

        if plain == "":
            dest[key] = ""
            return

        snippet = self.vault_handler.encrypt_string(plain, key)
        lines = snippet.splitlines()
        indent = len(lines[1]) - len(lines[1].lstrip())
        body = "\n".join(line[indent:] for line in lines[1:])
        dest[key] = VaultScalar(body)
