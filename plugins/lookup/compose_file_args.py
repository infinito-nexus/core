# lookup_plugins/compose_file_args.py
#
# Build compose "-f <file>" arguments for an application instance.
#
# HARD FAIL PRINCIPLE:
# - No silent defaults that change behavior.
# - Fail loudly if required variables are missing/invalid.
#
# Rules:
# - Always include base compose.yml
# - Include compose.override.yml ONLY when the ROLE (application_id) provides one
#   (same logic as tasks/04_files.yml with_first_found)
# - Include compose.ca.override.yml ONLY when:
#     the app has a domain AND TLS is enabled AND TLS mode == "self_signed"
#
# Optional kwargs:
# - include_ca (bool, default True):
#     - True  -> normal behavior (append CA override when enabled+self_signed)
#     - False -> do NOT append CA override (used during CA-inject bootstrap)
#
# IMPORTANT (your requested change):
# - This lookup NO LONGER reads variables['compose'].
# - It ALWAYS builds compose paths via utils.docker.paths_utils.get_docker_paths()
#   using DIR_COMPOSITIONS.

from __future__ import annotations

import os
from typing import Any, Optional

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase
from ansible.plugins.loader import lookup_loader

from utils.docker.paths_utils import get_docker_paths
from utils.jinja_strict import render_strict
from utils.cache.domains import get_merged_domains


def _as_str(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _require_dict(d: Any, label: str) -> dict:
    if not isinstance(d, dict):
        raise AnsibleError(f"compose_file_args: {label} must be a dict, got {type(d)}")
    return d


def _maybe_template(templar: Any, value: Any) -> Any:
    """
    Render via Ansible templar if available.
    Unit tests may not inject a templar -> then we skip templating.
    """
    if isinstance(value, (dict, list, tuple, int, float, bool)) or value is None:
        return value
    if templar is None:
        return value
    tpl = getattr(templar, "template", None)
    if callable(tpl):
        return tpl(value)
    return value


def _value_has_domain(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip() != ""
    if isinstance(v, (list, tuple, set)):
        return any(_value_has_domain(x) for x in v)
    if isinstance(v, dict):
        return any(_value_has_domain(x) for x in v.values())
    return False


def _has_domain(domains: Any, application_id: str) -> bool:
    """
    Dependency-free domain existence check that matches the intent of the old filter.
    """
    if isinstance(domains, dict):
        return _value_has_domain(domains.get(application_id))
    return _value_has_domain(domains)


def _role_provides_override(*, application_id: str, templar: Any) -> bool:
    """
    Mirror tasks/04_files.yml "with_first_found" logic:

      - "{{ application_id | abs_role_path_by_application_id }}/templates/compose.override.yml.j2"
      - "{{ application_id | abs_role_path_by_application_id }}/files/compose.override.yml"

    Only if one of these exists, we append "-f <compose.files.compose_override>".
    """
    tpl = getattr(templar, "template", None)
    if not callable(tpl):
        raise AnsibleError(
            "compose_file_args: templar is required to resolve abs_role_path_by_application_id"
        )

    role_base = _as_str(tpl("{{ application_id | abs_role_path_by_application_id }}"))
    if not role_base:
        raise AnsibleError(
            "compose_file_args: abs_role_path_by_application_id resolved to empty"
        )

    c1 = os.path.join(role_base, "templates", "compose.override.yml.j2")
    c2 = os.path.join(role_base, "files", "compose.override.yml")

    return os.path.isfile(c1) or os.path.isfile(c2)


class LookupModule(LookupBase):
    def run(self, terms, variables: Optional[dict] = None, **kwargs):
        variables = variables or {}

        if not terms or len(terms) != 1:
            raise AnsibleError(
                "compose_file_args: exactly one term required (application_id)"
            )

        application_id = _as_str(terms[0])
        if not application_id:
            raise AnsibleError("compose_file_args: application_id is empty")

        include_ca = kwargs.get("include_ca", True)
        if not isinstance(include_ca, bool):
            raise AnsibleError("compose_file_args: include_ca must be a bool")

        templar = getattr(self, "_templar", None)

        # ALWAYS build compose via utils (no dependency on variables['compose'])
        base_dir = _as_str(variables.get("DIR_COMPOSITIONS"))
        if not base_dir:
            raise AnsibleError(
                "compose_file_args: missing required variable 'DIR_COMPOSITIONS'"
            )

        compose = get_docker_paths(application_id, base_dir)
        compose = _require_dict(compose, "compose")

        files = _require_dict(compose.get("files"), "compose.files")

        # Use strict rendering to ensure we never leak "{{ ... }}" into generated commands.
        base = render_strict(
            files.get("compose"),
            variables=variables,
            var_name="compose.files.compose",
            err_prefix="compose_file_args",
        )
        override = render_strict(
            files.get("compose_override"),
            variables=variables,
            var_name="compose.files.compose_override",
            err_prefix="compose_file_args",
        )
        ca_override = render_strict(
            files.get("compose_ca_override"),
            variables=variables,
            var_name="compose.files.compose_ca_override",
            err_prefix="compose_file_args",
        )

        if not _as_str(base):
            raise AnsibleError("compose_file_args: compose.files.compose is required")

        parts = [f"-f {base}"]

        # 1) Append override ONLY if the ROLE provides it (same logic as 04_files.yml).
        if _role_provides_override(application_id=application_id, templar=templar):
            if not _as_str(override):
                raise AnsibleError(
                    "compose_file_args: compose.files.compose_override is required "
                    "when the role provides an override file"
                )
            parts.append(f"-f {override}")

        # 2) CA override: only when include_ca=True and domain exists AND TLS is enabled AND self_signed.
        if include_ca:
            domains = get_merged_domains(
                variables=variables,
                roles_dir=kwargs.get("roles_dir"),
                templar=templar,
            )
            if _has_domain(domains, application_id):
                tlsr = lookup_loader.get("tls", self._loader, self._templar)
                tls = tlsr.run([application_id], variables=variables)[0]

                if not isinstance(tls, dict):
                    raise AnsibleError(
                        f"compose_file_args: tls returned non-dict: {type(tls)}"
                    )
                if "enabled" not in tls:
                    raise AnsibleError(
                        "compose_file_args: tls did not return 'enabled'"
                    )
                if "mode" not in tls:
                    raise AnsibleError("compose_file_args: tls did not return 'mode'")

                enabled = bool(tls["enabled"])
                mode = _as_str(tls["mode"])
                if not mode:
                    raise AnsibleError("compose_file_args: tls returned empty 'mode'")

                if enabled and mode == "self_signed":
                    if not _as_str(ca_override):
                        raise AnsibleError(
                            "compose_file_args: compose.files.compose_ca_override is required "
                            "when TLS is enabled and mode is self_signed"
                        )
                    parts.append(f"-f {ca_override}")

        return [" ".join(parts)]
