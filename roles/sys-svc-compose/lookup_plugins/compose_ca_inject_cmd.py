from __future__ import annotations

from pathlib import Path
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.roles.entity_name import get_entity_name
from utils.templating.ansible import render_ansible_strict


def _as_str(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _require(d: Any, key: str, expected_type: Any, *, label: str) -> Any:
    if not isinstance(d, dict):
        raise AnsibleError(
            f"compose_ca_inject_cmd: {label} must be a dict, got {type(d)}"
        )
    if key not in d:
        raise AnsibleError(f"compose_ca_inject_cmd: missing required {label} '{key}'")
    val = d[key]
    if not isinstance(val, expected_type):
        raise AnsibleError(
            f"compose_ca_inject_cmd: {label} '{key}' must be {expected_type}, got {type(val)}"
        )
    return val


def _shell_quote(s: str) -> str:
    # Safe single-quote shell quoting: ' -> '"'"'
    return "'" + s.replace("'", "'\"'\"'") + "'"


def _env_file_if_exists(instance_dir_s: str, env_file_s: str) -> str:
    """
    Only return env file path if it exists.

    - If env_file_s is relative, resolve it against the compose instance directory.
    - Returns "" if missing.
    """
    env_file_s = (env_file_s or "").strip()
    if not env_file_s:
        return ""

    p = Path(env_file_s)
    if not p.is_absolute():
        p = Path(instance_dir_s) / p

    return str(p) if p.is_file() else ""


def _docker_lookup(
    lookup: LookupBase,
    *,
    application_id: str,
    key: str,
    variables: dict,
) -> str:
    """
    Call lookup('container', application_id, '<key>') from inside this lookup plugin.
    """
    docker_lkp = lookup_loader.get("container", lookup._loader, lookup._templar)
    try:
        value = docker_lkp.run([application_id, key], variables=variables)[0]
    except Exception as exc:
        raise AnsibleError(
            f"compose_ca_inject_cmd: docker lookup failed for '{key}': {exc}"
        ) from exc
    return _as_str(value)


class LookupModule(LookupBase):
    def run(self, terms, variables: dict | None = None, **kwargs):
        variables = variables or {}

        # ---------------------------------------------------------------------
        # Validate input
        # ---------------------------------------------------------------------
        if not terms or len(terms) != 1:
            raise AnsibleError(
                "compose_ca_inject_cmd: exactly one term required (application_id)"
            )

        application_id = _as_str(terms[0])
        if not application_id:
            raise AnsibleError("compose_ca_inject_cmd: application_id is empty")

        wrapper = kwargs.get("wrapper", True)
        if not isinstance(wrapper, bool):
            raise AnsibleError("compose_ca_inject_cmd: wrapper must be a bool")

        project = _as_str(get_entity_name(application_id))
        if not project:
            raise AnsibleError("compose_ca_inject_cmd: resolved project is empty")

        templar = getattr(self, "_templar", None)

        # ---------------------------------------------------------------------
        # Resolve compose paths via lookup('container', ...)
        # ---------------------------------------------------------------------
        instance_dir = _docker_lookup(
            self,
            application_id=application_id,
            key="directories.instance",
            variables=variables,
        )
        env_file = _docker_lookup(
            self,
            application_id=application_id,
            key="files.env",
            variables=variables,
        )
        out_file = _docker_lookup(
            self,
            application_id=application_id,
            key="files.compose_ca_override",
            variables=variables,
        )

        if not instance_dir:
            raise AnsibleError(
                "compose_ca_inject_cmd: resolved directories.instance is empty"
            )
        if not out_file:
            raise AnsibleError(
                "compose_ca_inject_cmd: resolved files.compose_ca_override is empty"
            )

        out_basename = Path(out_file).name
        if not out_basename:
            raise AnsibleError(
                "compose_ca_inject_cmd: output basename resolved to empty"
            )

        # ---------------------------------------------------------------------
        # CA_TRUST variables
        # ---------------------------------------------------------------------
        ca_trust = _require(variables, "CA_TRUST", dict, label="variable")

        script_path = render_ansible_strict(
            templar=templar,
            raw=_require(ca_trust, "inject_script", str, label="CA_TRUST"),
            var_name="CA_TRUST.inject_script",
            err_prefix="compose_ca_inject_cmd",
            variables=variables,
        )
        ca_host = render_ansible_strict(
            templar=templar,
            raw=_require(ca_trust, "cert_host", str, label="CA_TRUST"),
            var_name="CA_TRUST.cert_host",
            err_prefix="compose_ca_inject_cmd",
            variables=variables,
        )
        wrapper_host = render_ansible_strict(
            templar=templar,
            raw=_require(ca_trust, "wrapper_host", str, label="CA_TRUST"),
            var_name="CA_TRUST.wrapper_host",
            err_prefix="compose_ca_inject_cmd",
            variables=variables,
        )
        trust_name = render_ansible_strict(
            templar=templar,
            raw=_require(ca_trust, "trust_name", str, label="CA_TRUST"),
            var_name="CA_TRUST.trust_name",
            err_prefix="compose_ca_inject_cmd",
            variables=variables,
        )

        # ---------------------------------------------------------------------
        # Resolve compose files (without CA override!)
        # ---------------------------------------------------------------------
        compose_file_args_lkp = lookup_loader.get(
            "compose_file_args", self._loader, self._templar
        )
        compose_files = compose_file_args_lkp.run(
            [application_id],
            variables=variables,
            include_ca=False,
        )[0]

        if not _as_str(compose_files):
            raise AnsibleError(
                "compose_ca_inject_cmd: compose_file_args returned empty"
            )

        # ---------------------------------------------------------------------
        # Build command
        # ---------------------------------------------------------------------
        cmd = [
            "python3",
            _shell_quote(script_path),
            "--chdir",
            _shell_quote(instance_dir),
            "--project",
            _shell_quote(project),
            "--compose-files",
            _shell_quote(compose_files),
        ]

        env_file_existing = _env_file_if_exists(instance_dir, env_file)
        if env_file_existing:
            cmd += ["--env-file", _shell_quote(env_file_existing)]

        cmd += [
            "--out",
            _shell_quote(out_basename),
            "--ca-host",
            _shell_quote(ca_host),
            "--wrapper-host",
            _shell_quote(wrapper_host),
            "--trust-name",
            _shell_quote(trust_name),
        ]

        if not wrapper:
            cmd += ["--no-wrapper"]

        return [" ".join(cmd)]
