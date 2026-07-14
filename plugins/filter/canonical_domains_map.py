from collections.abc import Iterable
from pathlib import Path

from ansible.errors import AnsibleError, AnsibleFilterError

from utils.domains.list import render_domain_value
from utils.roles.dependency_resolver import RoleDependencyResolver
from utils.roles.entity.name import get_entity_name
from utils.templating.ansible import render_ansible_strict


def _resolve_domain_primary(domain_primary):
    if not isinstance(domain_primary, str):
        return domain_primary
    if "{{" not in domain_primary and "{%" not in domain_primary:
        return domain_primary
    try:
        return render_ansible_strict(
            templar=None,
            raw=domain_primary,
            var_name="DOMAIN_PRIMARY",
            err_prefix="canonical_domains_map",
            variables={},
        )
    except AnsibleError as e:
        raise AnsibleFilterError(
            f"canonical_domains_map: failed to resolve DOMAIN_PRIMARY {domain_primary!r}: {e}"
        ) from e


class FilterModule:
    def filters(self):
        return {"canonical_domains_map": self.canonical_domains_map}

    def canonical_domains_map(
        self,
        apps,
        domain_primary,
        *,
        recursive: bool = False,
        roles_base_dir: str | None = None,
        seed: Iterable[str] | None = None,
    ):
        """
        Build { app_id: [canonical domains...] }.

        Rekursiv werden nur include_role, import_role und meta/main.yml:dependencies verfolgt.
        'run_after' wird hier absichtlich ignoriert.
        """
        if not isinstance(apps, dict):
            raise AnsibleFilterError(
                f"'apps' must be a dict, got {type(apps).__name__}"
            )

        domain_primary = _resolve_domain_primary(domain_primary)

        app_keys = set(apps.keys())
        seed_keys = set(seed) if seed is not None else app_keys

        if recursive:
            roles_base_dir = roles_base_dir or str(Path(str(Path.cwd())) / "roles")
            if not Path(roles_base_dir).is_dir():
                raise AnsibleFilterError(
                    f"roles_base_dir '{roles_base_dir}' not found or not a directory."
                )

            resolver = RoleDependencyResolver(roles_base_dir)
            discovered_roles = resolver.resolve_transitively(
                start_roles=seed_keys,
                resolve_include_role=True,
                resolve_import_role=True,
                resolve_dependencies=True,
                resolve_run_after=False,
                max_depth=None,
            )
            target_apps = discovered_roles & app_keys
        else:
            target_apps = seed_keys

        result = {}
        seen_domains = {}

        auto_default_prefixes = ("web-", "svc-db-")

        for app_id in sorted(target_apps):
            cfg = apps.get(app_id)
            if cfg is None:
                continue

            is_auto_default = str(app_id).startswith(auto_default_prefixes)
            has_canonical = (
                isinstance(cfg, dict)
                and isinstance(cfg.get("domains"), dict)
                and "canonical" in cfg["domains"]
            )

            if not has_canonical and not is_auto_default:
                continue

            if not isinstance(cfg, dict):
                raise AnsibleFilterError(
                    f"Invalid configuration for application '{app_id}': expected dict, got {cfg!r}"
                )

            if not has_canonical:
                self._add_default_domain(app_id, domain_primary, seen_domains, result)
                continue

            domains_cfg = cfg["domains"]

            canonical_domains = render_domain_value(
                domains_cfg["canonical"],
                {"DOMAIN_PRIMARY": domain_primary},
                f"{app_id}.domains.canonical",
            )
            self._process_canonical_domains(
                app_id, canonical_domains, seen_domains, result
            )

        return result

    def _add_default_domain(self, app_id, domain_primary, seen_domains, result):
        entity_name = get_entity_name(app_id)
        dp = str(domain_primary)
        if "{{" in dp or "}}" in dp or "{%" in dp:
            raise AnsibleFilterError(
                f"canonical_domains_map: domain_primary is not rendered "
                f"(contains Jinja expression): {domain_primary!r}"
            )
        default_domain = f"{entity_name}.{dp}"
        if default_domain in seen_domains:
            raise AnsibleFilterError(
                f"Domain '{default_domain}' is already configured for "
                f"'{seen_domains[default_domain]}' and '{app_id}'"
            )
        seen_domains[default_domain] = app_id
        result[app_id] = [default_domain]

    def _process_canonical_domains(
        self, app_id, canonical_domains, seen_domains, result
    ):
        if isinstance(canonical_domains, dict):
            for domain in canonical_domains.values():
                self._validate_and_check_domain(app_id, domain, seen_domains)
            result[app_id] = canonical_domains.copy()
        elif isinstance(canonical_domains, list):
            for domain in canonical_domains:
                self._validate_and_check_domain(app_id, domain, seen_domains)
            result[app_id] = list(canonical_domains)
        else:
            raise AnsibleFilterError(
                f"Unexpected type for 'domains.canonical' in application '{app_id}': "
                f"{type(canonical_domains).__name__}"
            )

    def _validate_and_check_domain(self, app_id, domain, seen_domains):
        if not isinstance(domain, str) or not domain.strip():
            raise AnsibleFilterError(
                f"Invalid domain entry in 'canonical' for application '{app_id}': {domain!r}"
            )
        if domain in seen_domains:
            raise AnsibleFilterError(
                f"Domain '{domain}' is already configured for '{seen_domains[domain]}' and '{app_id}'"
            )
        seen_domains[domain] = app_id
