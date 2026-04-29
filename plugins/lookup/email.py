from __future__ import annotations

from typing import Any, Dict, Optional

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from plugins.lookup.applications import LookupModule as ApplicationsLookup
from plugins.lookup.domain import LookupModule as DomainLookup
from plugins.lookup.users import LookupModule as UsersLookup


SYSTEM_EMAIL_PREFIX = "SYSTEM_EMAIL_"

# Declared in resolution order so each computed default sees already-resolved
# predecessors (for example ``port`` depends on ``tls``).
RESOLUTION_ORDER = (
    "enabled",
    "timeout",
    "external",
    "environment",
    "domain",
    "tls",
    "port",
    "host",
    "auth",
    "start_tls",
    "smtp",
    "from",
    "username",
    "password",
)

_TRUE_STRINGS = frozenset({"true", "yes", "1", "on"})
_FALSE_STRINGS = frozenset({"false", "no", "0", "off"})


def _short_to_var(short_key: str) -> str:
    return SYSTEM_EMAIL_PREFIX + short_key.upper()


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _TRUE_STRINGS:
            return True
        if lowered in _FALSE_STRINGS:
            return False
    return bool(value)


def _render(value: Any, templar: Optional[Any]) -> Any:
    if templar is None:
        return value
    if not isinstance(value, str) or "{{" not in value:
        return value
    try:
        return templar.template(value, fail_on_undefined=False)
    except Exception:
        return value


class LookupModule(LookupBase):
    def run(
        self,
        terms: Optional[list[Any]],
        variables: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> list[Any]:
        terms = terms or []
        if len(terms) > 1:
            raise AnsibleError(
                "email: expected 0 or 1 terms: lookup('email'[, application_id])"
            )

        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        self._kwargs = kwargs

        templar = getattr(self, "_templar", None)
        resolved: Dict[str, Any] = {}
        for short_key in RESOLUTION_ORDER:
            var_name = _short_to_var(short_key)
            raw = variables.get(var_name)
            if raw is None or raw == "":
                resolved[short_key] = _render(
                    self._compute(short_key, resolved, variables), templar
                )
            else:
                resolved[short_key] = _render(raw, templar)

        if len(terms) == 0:
            return [resolved]

        application_id = str(terms[0]).strip()
        overrides = self._app_email_overrides(application_id, variables)
        merged = dict(resolved)
        for key, value in overrides.items():
            merged[str(key).lower()] = _render(value, templar)
        return [merged]

    def _compute(
        self,
        short_key: str,
        resolved: Dict[str, Any],
        variables: Dict[str, Any],
    ) -> Any:
        if short_key == "enabled":
            return True
        if short_key == "timeout":
            return "30"
        if short_key == "external":
            group_names = variables.get("group_names") or []
            return bool("web-app-mailu" in group_names)
        if short_key == "environment":
            external = _as_bool(resolved.get("external"))
            tls_enabled = _as_bool(variables.get("TLS_ENABLED"))
            docker_in_container = _as_bool(variables.get("DOCKER_IN_CONTAINER"))
            base = "external" if (external or tls_enabled) else "localhost"
            suffix = "_container" if (docker_in_container and not tls_enabled) else ""
            return base + suffix
        if short_key == "domain":
            return variables.get("DOMAIN_PRIMARY")
        if short_key == "tls":
            external = _as_bool(resolved.get("external"))
            if not external:
                return False
            return _as_bool(variables.get("TLS_ENABLED"))
        if short_key == "port":
            external = _as_bool(resolved.get("external"))
            tls = _as_bool(resolved.get("tls"))
            return 465 if (external and tls) else 25
        if short_key == "host":
            env = resolved.get("environment")
            if env in ("external_container", "localhost", "localhost_container"):
                return "localhost"
            return self._lookup_mailu_domain(variables)
        if short_key == "auth":
            env = resolved.get("environment")
            if env in ("external_container", "localhost"):
                return False
            return _as_bool(resolved.get("tls"))
        if short_key == "start_tls":
            return False
        if short_key == "smtp":
            return True
        if short_key == "from":
            external = _as_bool(resolved.get("external"))
            if external:
                no_reply = self._lookup_no_reply_user(variables)
                if isinstance(no_reply, dict):
                    email = no_reply.get("email")
                    if email:
                        return email
            inventory_hostname = variables.get("inventory_hostname") or "localhost"
            return f"root@{inventory_hostname}.localdomain"
        if short_key == "username":
            return resolved.get("from")
        if short_key == "password":
            no_reply = self._lookup_no_reply_user(variables)
            if isinstance(no_reply, dict):
                tokens = no_reply.get("tokens") or {}
                if isinstance(tokens, dict):
                    return tokens.get("web-app-mailu", "") or ""
            return ""
        raise AnsibleError(f"email: unknown key {short_key!r}")

    def _lookup_mailu_domain(self, variables: Dict[str, Any]) -> Any:
        domain_lookup = DomainLookup()
        domain_lookup._templar = getattr(self, "_templar", None)
        try:
            return domain_lookup.run(["web-app-mailu"], variables=variables)[0]
        except Exception:
            return "localhost"

    def _lookup_no_reply_user(self, variables: Dict[str, Any]) -> Dict[str, Any]:
        users_lookup = UsersLookup()
        users_lookup._templar = getattr(self, "_templar", None)
        forwarded = {
            k: v for k, v in getattr(self, "_kwargs", {}).items() if k == "roles_dir"
        }
        try:
            entry = users_lookup.run(
                ["no-reply", {}], variables=variables, **forwarded
            )[0]
        except AnsibleError:
            return {}
        return entry if isinstance(entry, dict) else {}

    def _app_email_overrides(
        self,
        application_id: str,
        variables: Dict[str, Any],
    ) -> Dict[str, Any]:
        apps = ApplicationsLookup()
        apps._templar = getattr(self, "_templar", None)
        forwarded = {
            k: v for k, v in getattr(self, "_kwargs", {}).items() if k == "roles_dir"
        }
        try:
            entry = apps.run(
                [application_id, {}],
                variables=variables,
                **forwarded,
            )[0]
        except AnsibleError:
            return {}
        if not isinstance(entry, dict):
            return {}
        # Per req-008 the materialised payload exposes services under the
        # bare ``services`` key (no ``compose.services`` envelope).
        services = entry.get("services") or {}
        email = services.get("email") or {} if isinstance(services, dict) else {}
        if not isinstance(email, dict):
            return {}
        return email
