from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Set

from utils.handler.yaml import YamlHandler
from utils.handler.vault import VaultHandler, VaultScalar
from utils.database_service import resolve_database_service_key
from utils.manager.value_generator import ValueGenerator
from utils.service_registry import (
    build_service_registry_from_roles_dir,
    resolve_service_dependency_roles_from_config,
)


# Marker fields that identify a credential schema leaf (per req-008). Any
# `default:` value is preserved verbatim; algorithm defaults to `plain` when
# absent; `validation:` only applies to user-provided values.
_CREDENTIAL_LEAF_MARKERS = ("description", "algorithm", "validation", "default")


def _is_credential_leaf(node: Any) -> bool:
    return isinstance(node, dict) and any(
        marker in node for marker in _CREDENTIAL_LEAF_MARKERS
    )


def _meta_role_config(role_path: Path) -> Dict[str, Any]:
    """Assemble the post-req-008 view of a role's config from its meta files.

    The shape mirrors the old `meta/services.yml` payload so that downstream
    helpers (database_service, service_registry, ...) keep working unchanged:
    `{services: <map>, server: <map>, rbac: <map>, volumes: <map>}`.
    """
    meta_dir = role_path / "meta"
    config: Dict[str, Any] = {}
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
        overrides: Dict[str, str],
        allow_empty_plain: bool = False,
    ):
        """Initialize the Inventory Manager."""
        self.role_path = role_path
        self.inventory_path = inventory_path
        self.vault_pw = vault_pw
        self.overrides = overrides
        self.allow_empty_plain = allow_empty_plain

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
        vars_file = role_path / "vars" / "main.yml"
        data = YamlHandler.load_yaml(vars_file) or {}
        app_id = data.get("application_id")
        if not app_id:
            print(f"ERROR: 'application_id' missing in {vars_file}", file=sys.stderr)
            sys.exit(1)
        return app_id

    @staticmethod
    def _load_role_schema_by_path(role_path: Path) -> Dict[str, Any]:
        schema_path = role_path / "meta" / "schema.yml"
        if not schema_path.exists():
            return {}
        return YamlHandler.load_yaml(schema_path) or {}

    def load_role_schema(self, role_name: str) -> Dict[str, Any]:
        return self._load_role_schema_by_path(self.roles_root / role_name)

    def load_role_config_by_path(self, role_path: Path) -> Dict[str, Any]:
        return _meta_role_config(role_path)

    def load_role_config(self, role_name: str) -> Dict[str, Any]:
        role_path = self.roles_root / role_name
        return self.load_role_config_by_path(role_path)

    # ---------------------------------------------------------------------
    # Shared provider resolution (recursive / transitive)
    # ---------------------------------------------------------------------

    def _direct_schema_includes_from_config(self, config: dict) -> List[str]:
        """
        Extract shared-provider dependencies from a single role config.
        """
        service_registry = build_service_registry_from_roles_dir(self.roles_root)
        return resolve_service_dependency_roles_from_config(config, service_registry)

    def resolve_schema_includes_recursive(self, root_role_name: str) -> List[str]:
        """
        Recursively resolve schema includes by following configs transitively.
        """
        resolved: List[str] = []
        seen: Set[str] = set()

        # seed with root role's direct includes
        root_cfg = self.load_role_config_by_path(self.role_path)
        queue: List[str] = self._direct_schema_includes_from_config(root_cfg)

        while queue:
            role_name = queue.pop(0)
            if role_name in seen:
                continue
            seen.add(role_name)
            resolved.append(role_name)

            cfg = self.load_role_config(role_name)
            for inc in self._direct_schema_includes_from_config(cfg):
                if inc not in seen:
                    queue.append(inc)

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
        oauth2 = services.get("oauth2") if isinstance(services, dict) else None
        oauth2 = oauth2 if isinstance(oauth2, dict) else {}
        oidc = services.get("oidc") if isinstance(services, dict) else None
        oidc = oidc if isinstance(oidc, dict) else {}
        has_database_service = bool(resolve_database_service_key({app_id: cfg}, app_id))
        if has_database_service:
            apps = self.inventory.setdefault("applications", {})
            target = apps.setdefault(app_id, {})
            target.setdefault("credentials", {})["database_password"] = (
                self.value_generator.generate_value("alphanumeric")
            )

        if oauth2.get("enabled") is True or oidc.get("enabled") is True:
            apps = self.inventory.setdefault("applications", {})
            target = apps.setdefault(app_id, {})
            target.setdefault("credentials", {})["oauth2_proxy_cookie_secret"] = (
                self.value_generator.generate_value("random_hex_16")
            )

    def apply_schema(self) -> Dict:
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

        Supports the post-req-008 schema:
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
            # Per req-008: write the literal Jinja string verbatim, no
            # rendering, no validation, no algorithm-based generation.
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
