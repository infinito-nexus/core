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
# - Include compose.ca.override.yml ONLY when lookup('ca_injected') is true
#
# Optional kwargs:
# - include_ca (bool, default True):
#     - True  -> normal behavior (append CA override when lookup('ca_injected') is true)
#     - False -> do NOT append CA override (used during CA-inject bootstrap)
#
# IMPORTANT (your requested change):
# - This lookup NO LONGER reads variables['compose'].
# - It ALWAYS builds compose paths via utils.docker.paths_utils.get_docker_paths()
#   using DIR_COMPOSITIONS.

from __future__ import annotations

from pathlib import Path
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from plugins.filter.role_path_by_app_id import abs_role_path_by_application_id
from utils.docker.paths_utils import get_docker_paths
from utils.templating.jinja import render_strict


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


def _role_provides_override(*, application_id: str) -> bool:
    """
    Mirror tasks/04_files.yml "with_first_found" logic:

      - "{{ application_id | abs_role_path_by_application_id }}/templates/compose.override.yml.j2"
      - "{{ application_id | abs_role_path_by_application_id }}/files/compose.override.yml"

    Only if one of these exists, we append "-f <compose.files.compose_override>".
    """
    role_base = Path(abs_role_path_by_application_id(application_id))
    return (role_base / "templates" / "compose.override.yml.j2").is_file() or (
        role_base / "files" / "compose.override.yml"
    ).is_file()


class LookupModule(LookupBase):
    def run(self, terms, variables: dict | None = None, **kwargs):
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

        flag = kwargs.get("flag", "-f")
        if flag not in ("-f", "--compose-file", "-c"):
            raise AnsibleError(
                "compose_file_args: flag must be one of -f, --compose-file, -c"
            )

        templar = getattr(self, "_templar", None)

        raw_base_dir = variables.get("DIR_COMPOSITIONS")
        if (
            isinstance(raw_base_dir, str)
            and "{{" in raw_base_dir
            and templar is not None
        ):
            raw_base_dir = templar.template(raw_base_dir)
        base_dir = _as_str(raw_base_dir)
        if not base_dir:
            raise AnsibleError(
                "compose_file_args: missing required variable 'DIR_COMPOSITIONS'"
            )

        compose = get_docker_paths(application_id, base_dir)
        compose = _require_dict(compose, "compose")

        files = _require_dict(compose.get("files"), "compose.files")

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

        parts = [f"{flag} {base}"]

        if _role_provides_override(application_id=application_id):
            if not _as_str(override):
                raise AnsibleError(
                    "compose_file_args: compose.files.compose_override is required "
                    "when the role provides an override file"
                )
            parts.append(f"{flag} {override}")

        if include_ca:
            injected = lookup_loader.get(
                "ca_injected", loader=self._loader, templar=templar
            ).run([application_id], variables=variables)[0]
            if injected:
                if not _as_str(ca_override):
                    raise AnsibleError(
                        "compose_file_args: compose.files.compose_ca_override is "
                        "required when the CA is injected"
                    )
                parts.append(f"{flag} {ca_override}")

        return [" ".join(parts)]
