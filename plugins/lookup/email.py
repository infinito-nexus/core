# nocheck: comments-valid  explanatory WHY-comments in this SPOT lookup predate the stricter lint
from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from plugins.lookup.applications import LookupModule as ApplicationsLookup
from plugins.lookup.domain import LookupModule as DomainLookup
from plugins.lookup.users import LookupModule as UsersLookup

SYSTEM_EMAIL_PREFIX = "SYSTEM_EMAIL_"

# Default mail provider role; overridable per inventory via the MAIL_PROVIDER var.
DEFAULT_MAIL_PROVIDER = "web-app-stalwart"

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


def _render(
    value: Any,
    templar: Any | None,
    variables: dict[str, Any] | None = None,
) -> Any:
    if templar is None:
        return value
    if not isinstance(value, str) or "{{" not in value:
        return value
    # Loop: inventory expressions like DOMAIN_PRIMARY="{{ lookup('env','INFINITO_DOMAIN') }}" need multiple substitution passes.
    from utils.templating.ansible import _templar_render_best_effort

    base_vars: dict[str, Any] = dict(variables or {})
    for _ in range(4):
        if not isinstance(value, str) or "{{" not in value:
            break
        prev = value
        try:
            value = _templar_render_best_effort(templar, value, base_vars)
        except Exception:
            break
        if value == prev:
            break
    return value


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
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
        resolved: dict[str, Any] = {}
        for short_key in RESOLUTION_ORDER:
            var_name = _short_to_var(short_key)
            raw = variables.get(var_name)
            if raw is None or raw == "":
                resolved[short_key] = _render(
                    self._compute(short_key, resolved, variables),
                    templar,
                    variables,
                )
            else:
                resolved[short_key] = _render(raw, templar, variables)

        if len(terms) == 0:
            return [resolved]

        application_id = str(terms[0]).strip()
        overrides = self._app_email_overrides(application_id, variables)
        merged = dict(resolved)
        for key, value in overrides.items():
            merged[str(key).lower()] = _render(value, templar, variables)
        return [merged]

    def _compute(
        self,
        short_key: str,
        resolved: dict[str, Any],
        variables: dict[str, Any],
    ) -> Any:
        if short_key == "enabled":
            return True
        if short_key == "timeout":
            return "30"
        if short_key == "external":
            # Cluster-wide, not per-host: in swarm the mail provider is
            # manager-pinned so worker group_names lack it, yet every node
            # relays through the central provider (routing mesh). Gate on the
            # group having a host so workers use the authenticated config, not
            # a localhost root sender the provider rejects
            # ("Sender address rejected: Domain not found").
            groups = variables.get("groups") or {}
            return bool(groups.get(self._mail_provider(variables)))
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
            # SSO relay: port 25 is the only listener not requiring SMTP AUTH.
            if self._provider_uses_sso_relay(variables):
                return 25
            return 465 if (external and tls) else 25
        if short_key == "host":
            env = resolved.get("environment")
            # `environment` folds TLS_ENABLED into its "external" base, so a
            # non-external relay under TLS would otherwise resolve to the mailu
            # domain while auth/tls/from stay in localhost mode -- an unreachable,
            # inconsistent render that aborts the msmtp health unit. Gate host on
            # `external` directly, like tls/auth/from do.
            if not _as_bool(resolved.get("external")) or env in (
                "external_container",
                "localhost",
                "localhost_container",
            ):
                return "localhost"
            return self._lookup_mail_provider_domain(variables)
        if short_key == "auth":
            env = resolved.get("environment")
            if env in ("external_container", "localhost"):
                return False
            if self._provider_uses_sso_relay(variables):
                return False
            return _as_bool(resolved.get("tls"))
        if short_key == "start_tls":
            # SSO relay uses STARTTLS on port 25.
            return self._provider_uses_sso_relay(variables)
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
                    return tokens.get(self._mail_provider(variables), "") or ""
            return ""
        raise AnsibleError(f"email: unknown key {short_key!r}")

    def _mail_provider(self, variables: dict[str, Any]) -> str:
        value = variables.get("MAIL_PROVIDER")
        return str(value).strip() if value else DEFAULT_MAIL_PROVIDER

    def _provider_uses_sso_relay(self, variables: dict[str, Any]) -> bool:
        """True when the active provider self-declares SSO relay (via
        ``services.sso.oidc.submission_via_relay``) and Keycloak is deployed."""
        group_names = variables.get("group_names") or []
        if "web-app-keycloak" not in group_names:
            return False
        apps = ApplicationsLookup()
        apps._templar = getattr(self, "_templar", None)
        forwarded = {
            k: v for k, v in getattr(self, "_kwargs", {}).items() if k == "roles_dir"
        }
        try:
            entry = apps.run(
                [self._mail_provider(variables), {}],
                variables=variables,
                **forwarded,
            )[0]
        except AnsibleError:
            return False
        if not isinstance(entry, dict):
            return False
        services = entry.get("services") or {}
        sso = services.get("sso") or {} if isinstance(services, dict) else {}
        oidc = sso.get("oidc") or {} if isinstance(sso, dict) else {}
        if not isinstance(oidc, dict):
            return False
        # A variant/inventory can pin the provider's sso.enabled to a literal
        # false while submission_via_relay stays true in the role defaults —
        # then the provider keeps password auth and never widens allowRelaying,
        # so relay mode must be off. Untemplated Jinja (the role default gates
        # on group_names) falls through to the Keycloak check above.
        enabled = sso.get("enabled") if isinstance(sso, dict) else None
        if enabled is not None and "{{" not in str(enabled) and not _as_bool(enabled):
            return False
        return _as_bool(oidc.get("submission_via_relay"))

    def _lookup_mail_provider_domain(self, variables: dict[str, Any]) -> Any:
        domain_lookup = DomainLookup()
        domain_lookup._templar = getattr(self, "_templar", None)
        try:
            return domain_lookup.run(
                [self._mail_provider(variables)], variables=variables
            )[0]
        except Exception:
            return "localhost"

    def _lookup_no_reply_user(self, variables: dict[str, Any]) -> dict[str, Any]:
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
        variables: dict[str, Any],
    ) -> dict[str, Any]:
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
        # Per the materialised payload exposes services under the
        # bare ``services`` key (no ``compose.services`` envelope).
        services = entry.get("services") or {}
        email = services.get("email") or {} if isinstance(services, dict) else {}
        if not isinstance(email, dict):
            return {}
        return email
