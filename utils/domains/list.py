from __future__ import annotations

from typing import TYPE_CHECKING, Any

from utils.cache.yaml import load_yaml as _load_yaml_cached
from utils.roles.mapping import ROLE_FILE_META_DOMAINS, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"


def _render_ansible_strict(
    *, raw: str, var_name: str, variables: dict[str, Any]
) -> str:
    from utils.templating.ansible import render_ansible_strict

    return render_ansible_strict(
        templar=None,
        raw=raw,
        var_name=var_name,
        err_prefix="domains.list",
        variables=variables,
    )


def _build_domain_index(
    applications: dict[str, Any], include_aliases: bool = True
) -> dict[str, str]:
    from utils.domains.application_domain_index import build_domain_index

    return build_domain_index(applications, include_aliases=include_aliases)


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return _load_yaml_cached(str(path), default_if_missing={})


def render_domain_value(value: Any, variables: dict[str, Any], field_name: str) -> Any:
    if isinstance(value, str):
        return _render_ansible_strict(
            raw=value,
            var_name=field_name,
            variables=variables,
        )

    if isinstance(value, list):
        return [
            render_domain_value(item, variables, f"{field_name}[{idx}]")
            for idx, item in enumerate(value)
        ]

    if isinstance(value, dict):
        return {
            key: render_domain_value(item, variables, f"{field_name}.{key}")
            for key, item in value.items()
        }

    return value


def build_applications_from_roles(
    roles_dir: Path, domain_primary: str
) -> dict[str, dict[str, Any]]:
    variables = {"DOMAIN_PRIMARY": domain_primary}
    applications: dict[str, dict[str, Any]] = {}

    for role_dir in sorted(roles_dir.iterdir()):
        vars_main = role_dir / ROLE_FILE_VARS_MAIN
        domains_meta = role_dir / ROLE_FILE_META_DOMAINS
        if not vars_main.exists() or not domains_meta.exists():
            continue

        vars_data = load_yaml_mapping(vars_main)
        application_id = vars_data.get("application_id")
        if not isinstance(application_id, str) or not application_id.strip():
            continue

        # The file-root of meta/domains.yml IS the value of
        # applications.<app>.domains.
        domains = load_yaml_mapping(domains_meta)
        if not isinstance(domains, dict):
            continue

        applications[application_id] = {
            "domains": render_domain_value(
                domains,
                variables,
                f"{application_id}.domains",
            )
        }

    return applications


def list_derived_domains(domain_primary: str) -> list[str]:
    primary = str(domain_primary).strip().lower()
    if not primary:
        return []

    # Keep non-role domains that are part of the stack contract in one place.
    return [f"test.{primary}"]


def add_www_variants(domains: list[str]) -> list[str]:
    expanded = set(domains)
    for domain in list(expanded):
        if not domain.startswith("www."):
            expanded.add(f"www.{domain}")
    return sorted(expanded)


def list_application_domains(
    domain_primary: str,
    *,
    include_aliases: bool = False,
    include_www: bool = False,
) -> list[str]:
    applications = build_applications_from_roles(ROLES_DIR, domain_primary)
    domains = set(
        _build_domain_index(applications, include_aliases=include_aliases).keys()
    )
    domains.update(list_derived_domains(domain_primary))
    sorted_domains = sorted(domains)
    if include_www:
        return add_www_variants(sorted_domains)
    return sorted_domains
