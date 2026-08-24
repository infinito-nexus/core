# Ansible lookup plugin to build versioned systemd unit names.
#
# Target format:
#   <service_name>.<version>.<software_domain><suffix>
#
# Examples:
#   lookup('unit_name', 'svc-foo')                       -> svc-foo.1.2.3.infinito.nexus.service
#   lookup('unit_name', 'sys-ctl-cln-bkps')              -> cln-bkps.1.2.3.infinito.nexus.service
#   lookup('unit_name', 'svc-foo', suffix='.timer')      -> svc-foo.1.2.3.infinito.nexus.timer
#   lookup('unit_name', 'alarm@')                        -> alarm.1.2.3.infinito.nexus@.service
#
# Requirements:
# - SOFTWARE_DOMAIN must be available in vars (inventory/group_vars/role vars).
# - Version is read via lookup('version') (your existing version lookup plugin).

from __future__ import annotations

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase


def _looks_like_template(value) -> bool:
    if not isinstance(value, str):
        return False
    return ("{{" in value) or ("{%" in value) or ("{#" in value)


def _render_if_template(templar, value, var_name: str):
    if not _looks_like_template(value):
        return value

    try:
        rendered = templar.template(value)
    except TypeError:
        rendered = templar.template(value)
    except Exception as exc:
        raise AnsibleError(
            f"unit_name lookup: failed to render template for '{var_name}': {value}"
        ) from exc

    if _looks_like_template(rendered):
        raise AnsibleError(
            f"unit_name lookup: unresolved template for '{var_name}': {value}"
        )
    return rendered


def _resolve_version(templar, variables):
    try:
        version = templar.template("{{ lookup('version') }}")
    except TypeError:
        version = templar.template("{{ lookup('version') }}")

    if _looks_like_template(version):
        try:
            try:
                from plugins.lookup.version import LookupModule as VersionLookupModule
            except ModuleNotFoundError:
                from version import LookupModule as VersionLookupModule

            version_lookup = VersionLookupModule()
            version_values = version_lookup.run([], variables=variables)
            if isinstance(version_values, list):
                version = version_values[0] if version_values else ""
            else:
                version = version_values
        except Exception as exc:
            raise AnsibleError(
                "unit_name lookup: failed to resolve version via lookup('version')."
            ) from exc

    return version


def _normalize_suffix(suffix) -> str:
    """
    Normalize suffix input to a systemd unit suffix string:
    - None / "" -> ".service"
    - False -> "" (no suffix)
    - "service" -> ".service"
    - ".timer" -> ".timer"
    """
    if suffix is False:
        return ""
    if suffix is None or str(suffix).strip() == "":
        return ".service"

    sfx = str(suffix).strip().lower()
    if not sfx.startswith("."):
        sfx = "." + sfx
    return sfx


def _lower_required(value, name: str) -> str:
    if value is None:
        raise AnsibleError(
            f"unit_name lookup: missing required variable '{name}' (is None)."
        )
    sval = str(value).strip()
    if not sval:
        raise AnsibleError(
            f"unit_name lookup: missing required variable '{name}' (empty)."
        )
    if _looks_like_template(sval):
        raise AnsibleError(
            f"unit_name lookup: unresolved template for '{name}': {sval}"
        )
    return sval.lower()


def _strip_sys_ctl_prefix(systemctl_id: str) -> str:
    prefix = "sys-ctl-"
    if systemctl_id.startswith(prefix):
        return systemctl_id[len(prefix) :]
    return systemctl_id


def _build_unit_name(
    systemctl_id: str, version: str, software_domain: str, suffix
) -> str:
    sid = _strip_sys_ctl_prefix(_lower_required(systemctl_id, "systemctl_id"))
    if not sid:
        raise AnsibleError(
            "unit_name lookup: normalized systemctl_id is empty after stripping prefix."
        )
    ver = _lower_required(version, "version")
    sw = _lower_required(software_domain, "SOFTWARE_DOMAIN")
    sfx = _normalize_suffix(suffix)

    if sid.endswith("@"):
        base = sid[:-1]
        return f"{base}.{ver}.{sw}@{sfx}"
    return f"{sid}.{ver}.{sw}{sfx}"


class LookupModule(LookupBase):
    """
    Lookup plugin entrypoint.

    Usage:
      - "{{ lookup('unit_name', system_service_id) }}"
      - "{{ lookup('unit_name', system_service_id, suffix='.timer') }}"
      - "{{ lookup('unit_name', system_service_id, suffix=False) }}"  # no suffix
    """

    def run(self, terms, variables=None, **kwargs):
        self.set_options(var_options=variables, direct=kwargs)

        if not terms:
            raise AnsibleError(
                "unit_name lookup: at least one term (systemctl_id) is required."
            )

        available = getattr(self._templar, "available_variables", {}) or {}
        software_domain = available.get("SOFTWARE_DOMAIN")
        if not software_domain:
            raise AnsibleError(
                "unit_name lookup: SOFTWARE_DOMAIN is not defined in the variable context."
            )
        software_domain = _render_if_template(
            self._templar, software_domain, "SOFTWARE_DOMAIN"
        )

        version = _resolve_version(self._templar, variables)
        if not version or not str(version).strip():
            raise AnsibleError(
                "unit_name lookup: lookup('version') returned an empty value."
            )

        suffix = kwargs.get("suffix")

        results = []
        results.extend(
            _build_unit_name(term, version, software_domain, suffix) for term in terms
        )

        return results
