# nocheck: comments-valid  explanatory WHY-comments in this SPOT lookup predate the stricter lint
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from plugins.lookup import PROJECT_ROOT
from plugins.lookup.applications import LookupModule as ApplicationsLookup
from plugins.lookup.domain import LookupModule as DomainLookup
from plugins.lookup.users import LookupModule as UsersLookup
from utils.cache.carrier import APPLICATIONS_RENDERED_FACT
from utils.domains.primary_domain import get_domain
from utils.mail.provider import (
    MAIL_SERVICE_KEY,
    active_provider,
    provider_deployed,
)
from utils.mail.provider_view import provider_view, view_carrier, view_id
from utils.networks.attachments import _is_consumer
from utils.networks.reachability import network, network_of
from utils.roles.applications.services.registry import discover_role_services
from utils.roles.entity.name import entity_name
from utils.tls.common import get_path

if TYPE_CHECKING:
    from collections.abc import Mapping

SYSTEM_EMAIL_PREFIX = "SYSTEM_EMAIL_"

# Declared in resolution order so each computed default sees already-resolved
# predecessors (for example ``port`` depends on ``tls``).
RESOLUTION_ORDER = (
    "enabled",
    "timeout",
    "external",
    "environment",
    "domain",
    "host",
    "tls",
    "port",
    "auth",
    "auth_mechanism",
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


def _with_rendered_provider(
    variables: Mapping[str, Any], templar: Any
) -> dict[str, Any]:
    """*variables* with ``MAIL_PROVIDER`` rendered.

    Args:
        variables: Ansible variables of the current host.
        templar: renders a templated ``MAIL_PROVIDER``; ``None`` takes it as is.
    """
    view = dict(variables)
    view["MAIL_PROVIDER"] = _render(variables.get("MAIL_PROVIDER"), templar, view)
    return view


def active_mail_provider(variables: Mapping[str, Any], templar: Any = None) -> str:
    """The mail provider role this deploy relays through.

    Args:
        variables: Ansible variables of the current host.
        templar: renders a templated ``MAIL_PROVIDER``; ``None`` takes it as is.
    """
    return active_provider(
        _with_rendered_provider(variables, templar), PROJECT_ROOT / "roles"
    )


def provider_view_carrier(
    variables: Mapping[str, Any],
    *,
    templar: Any,
    roles_dir: str | None = None,
) -> dict[str, Any] | None:
    """Render the applications payload of `provider_view` for a host that does
    not run the provider.

    Args:
        variables: Ansible variables of the current host.
        templar: templar the view renders with; its available variables are
            the view for the duration of the render.
        roles_dir: roles tree to build from; the repository's when ``None``.

    Returns:
        ``{"key", "applications", "view"}`` to park in
        `PROVIDER_VIEW_RENDERED_FACT`, or ``None`` when this host is the
        provider host `provider_view` picks, no provider host serves onion,
        or the parked payload or the provider host's own carrier still
        matches the view.
    """
    resolved = provider_view(variables, active_mail_provider(variables, templar))
    if resolved is None:
        return None
    host, view = resolved
    if host == variables.get("inventory_hostname"):
        return None
    view.pop("application_id", None)
    if view_carrier(variables, host, view, roles_dir) is not None:
        return None
    applications = ApplicationsLookup()
    applications._templar = templar
    previous = templar.available_variables
    templar.available_variables = view
    try:
        carrier = applications.run(
            [], variables=view, roles_dir=roles_dir, carrier=True
        )[0]
    finally:
        templar.available_variables = previous
    return {**carrier, "view": view_id(host, view)}


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        """Resolve the system mail settings.

        Args:
            terms: empty, or one application_id whose ``services.email``
                overrides are merged in.
            variables: Ansible variables of the current host.
            key: optional entry of RESOLUTION_ORDER; returns only that value,
                resolving its predecessors but none of the later keys.

        Returns:
            One-element list: the settings mapping, or the value of ``key``.
        """
        terms = terms or []
        if len(terms) > 1:
            raise AnsibleError(
                "email: expected 0 or 1 terms: lookup('email'[, application_id])"
            )

        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        requested = kwargs.pop("key", None)
        if requested is not None and requested not in RESOLUTION_ORDER:
            raise AnsibleError(
                f"email: unknown key {requested!r}, expected one of "
                f"{', '.join(RESOLUTION_ORDER)}"
            )
        self._kwargs = kwargs

        templar = getattr(self, "_templar", None)
        resolved: dict[str, Any] = {}
        last = requested if len(terms) == 0 else None
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
            if short_key == last:
                break

        if len(terms) == 0:
            return [resolved if requested is None else resolved[requested]]

        application_id = str(terms[0]).strip()
        overrides = self._app_email_overrides(application_id, variables)
        merged = dict(resolved)
        merged.update(self._internal_submission(application_id, resolved, variables))
        for key, value in overrides.items():
            merged[str(key).lower()] = _render(value, templar, variables)
        return [merged if requested is None else merged[requested]]

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
            return provider_deployed(
                _with_rendered_provider(variables, getattr(self, "_templar", None)),
                PROJECT_ROOT / "roles",
            )
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
            mail_host = str(resolved.get("host") or "").lower()
            if not network(network_of(mail_host)).tls or self._provider_onion_primary(
                variables
            ):
                return False
            return _as_bool(variables.get("TLS_ENABLED"))
        if short_key == "port":
            external = _as_bool(resolved.get("external"))
            if not external:
                return 25
            ports = self._provider_ports(variables, "public")
            if _as_bool(resolved.get("tls")):
                return ports.get("smtps", 465)
            # Plaintext submission is the onion/no-TLS path, but a provider is
            # only reachable there if it binds one. Stalwart's default config
            # binds the implicit-TLS client ports plus the MX, so it advertises
            # no `submission`; fall back to the MX port rather than a listener
            # nothing answers on (`auth` drops with it -- an MX takes local
            # recipients without SMTP AUTH).
            return ports.get("submission") or ports.get("smtp", 25)
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
            # The MX listener offers no SMTP AUTH: when `port` fell back to it
            # because the provider binds no plaintext submission, announcing
            # AUTH aborts msmtp with EX_UNAVAILABLE before it ever sends.
            ports = self._provider_ports(variables, "public")
            if not ports.get("submission") and resolved.get("port") == ports.get(
                "smtp", 25
            ):
                return False
            return _as_bool(resolved.get("external"))
        if short_key == "auth_mechanism":
            if not _as_bool(resolved.get("auth")):
                return "off"
            return "on" if _as_bool(resolved.get("tls")) else "plain"
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
                    return tokens.get(self._mail_provider(variables), "") or ""
            return ""
        raise AnsibleError(f"email: unknown key {short_key!r}")

    def _mail_provider(self, variables: dict[str, Any]) -> str:
        return active_mail_provider(variables, getattr(self, "_templar", None))

    def _application(
        self, application_id: str, variables: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Args:
            application_id: the application to read.
            variables: Ansible variables of the current host.

        Returns:
            Its applications entry, or ``{}`` when it cannot be resolved.
        """
        apps = ApplicationsLookup()
        apps._templar = getattr(self, "_templar", None)
        forwarded = {
            k: v for k, v in getattr(self, "_kwargs", {}).items() if k == "roles_dir"
        }
        try:
            entry = apps.run([application_id, {}], variables=variables, **forwarded)[0]
        except AnsibleError:
            return {}
        return entry if isinstance(entry, dict) else {}

    def _provider_services(self, variables: dict[str, Any]) -> dict[str, Any]:
        services = (
            self._application(self._mail_provider(variables), variables).get("services")
            or {}
        )
        return services if isinstance(services, dict) else {}

    def _internal_submission(
        self,
        application_id: str,
        resolved: dict[str, Any],
        variables: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Args:
            application_id: the application the lookup resolves for.
            resolved: the system settings resolved so far.
            variables: Ansible variables of the current host.

        Returns:
            ``host`` (the provider's service name), ``port``, ``tls``,
            ``start_tls``, ``auth`` and ``auth_mechanism`` of plaintext
            submission with ``AUTH PLAIN``, or ``{}`` when the relay keeps
            TLS, the provider publishes its submission port or binds none,
            *application_id* is a mail provider itself, or it does not join
            the provider's network.
        """
        if not _as_bool(resolved.get("external")) or _as_bool(resolved.get("tls")):
            return {}
        if self._provider_ports(variables, "public").get("submission"):
            return {}
        port = self._provider_ports(variables, "internal").get("submission")
        if not port:
            return {}
        own = discover_role_services(
            application_id, self._application(application_id, variables)
        ).get(entity_name(application_id))
        if MAIL_SERVICE_KEY in (own or {}).get("covers", []):
            return {}
        provider = self._mail_provider(variables)
        entity = entity_name(provider)
        network = discover_role_services(
            provider, self._application(provider, variables)
        ).get(entity)
        if not network or not _is_consumer(
            network,
            application_id,
            lambda app, path, default: get_path(
                self._application(app, variables), path, default
            ),
            lambda _app, _key: None,
        ):
            return {}
        return {
            "host": entity,
            "port": port,
            "tls": False,
            "start_tls": False,
            "auth": True,
            "auth_mechanism": "plain",
        }

    def _provider_ports(self, variables: dict[str, Any], group: str) -> dict[str, int]:
        """
        Args:
            variables: Ansible variables of the current host.
            group: ``public`` for the ports it publishes, ``internal`` for
                the ports its container binds.

        Returns:
            The SMTP ports of the active provider's own
            ``services.<entity>.ports.<group>``, keyed by protocol.
        """
        services = self._provider_services(variables)
        entity = entity_name(self._mail_provider(variables))
        entry = services.get(entity) or {}
        if not isinstance(entry, dict):
            return {}
        ports = (entry.get("ports") or {}).get(group) or {}
        if not isinstance(ports, dict):
            return {}
        out: dict[str, int] = {}
        for name, value in ports.items():
            try:
                out[str(name)] = int(value)
            except (TypeError, ValueError):
                continue
        return out

    def _provider_onion_primary(self, variables: dict[str, Any]) -> bool:
        """True when the provider's own host serves it onion-first.

        Resolved from the provider host's ``group_names`` and ``NETWORK_MODE``
        rather than this host's: in swarm only the manager is in
        ``svc-net-tor``, and the provider's ``tor.enabled`` renders against
        ``group_names``, so a worker would otherwise see the clearnet name the
        provider never serves a certificate for.
        """
        provider = self._mail_provider(variables)
        resolved = provider_view(variables, provider)
        if resolved is None:
            return False
        host, view = resolved
        forwarded = {
            k: v for k, v in getattr(self, "_kwargs", {}).items() if k == "roles_dir"
        }
        carrier = view_carrier(variables, host, view, forwarded.get("roles_dir"))
        if carrier is not None:
            view[APPLICATIONS_RENDERED_FACT] = carrier
        try:
            domains = lookup_loader.get(
                "domains",
                loader=getattr(self, "_loader", None),
                templar=getattr(self, "_templar", None),
            ).run([], variables=view, **forwarded)[0]
            domain = get_domain(domains, provider)
        except Exception:
            return False
        return not network(network_of(domain)).tls

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
        services = self._application(application_id, variables).get("services") or {}
        email = services.get("email") or {} if isinstance(services, dict) else {}
        if not isinstance(email, dict):
            return {}
        return email
