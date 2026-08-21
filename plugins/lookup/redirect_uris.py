from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.get_url import get_url
from utils.roles.applications.config import (
    AppConfigKeyError,
    ConfigEntryNotSetError,
    get,
)
from utils.tls_common import resolve_enabled

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

DEFAULT_FEATURES = ("services.sso.enabled",)
DEFAULT_WILDCARD = "/*"


def _stable_dedup(items: Sequence[str]) -> list[str]:
    seen = set()
    out: list[str] = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _iter_domains(value: Any) -> Iterable[str]:
    """Yield domains from str | list/tuple[str] | dict[*, str|list|tuple]."""
    if value is None:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for val in value.values():
            yield from _iter_domains(val)
    elif isinstance(value, (list, tuple)):
        for val in value:
            yield from _iter_domains(val)
    else:
        raise AnsibleError(
            "redirect_uris: domain value must be str, list/tuple[str], or dict mapping to those"
        )


def build_redirect_uris(
    domains: dict,
    applications: dict,
    tls_enabled: bool,
    *,
    wildcard: str = DEFAULT_WILDCARD,
    features: Iterable[str] = DEFAULT_FEATURES,
    dedup: bool = True,
) -> list[str]:
    """Registered redirect URIs for every SSO consumer, one per domain.

    Args:
        domains: app_id -> domain, list of domains, or nested mapping of those.
        applications: merged applications view, used for feature gating and for
            each consumer's ``server.tls.enabled`` override.
        tls_enabled: global TLS default, overridden per consumer by
            ``resolve_enabled``; an .onion domain always resolves to plaintext.
        wildcard: suffix appended to every URI.
        features: config paths ORed together to decide whether an app gets a URI.
        dedup: drop repeated URIs, preserving first-seen order.
    """
    if not isinstance(domains, dict):
        raise AnsibleError(
            "redirect_uris: 'domains' must be a dict mapping app_id -> domain or list of domains"
        )

    uris: list[str] = []
    for app_id, domain_value in domains.items():
        try:
            has_feature = any(
                bool(get(applications, app_id, f, False)) for f in features
            )
        except (AppConfigKeyError, ConfigEntryNotSetError):
            has_feature = False
        if not has_feature:
            continue

        for domain in _iter_domains(domain_value):
            proto = (
                "https"
                if resolve_enabled(
                    applications.get(app_id) or {}, tls_enabled, primary_domain=domain
                )
                else "http"
            )
            try:
                url = get_url({app_id: domain}, app_id, proto)
            except Exception as exc:
                raise AnsibleError(
                    f"redirect_uris: get_url failed for app '{app_id}' "
                    f"with domain '{domain}': {exc}"
                ) from exc
            uris.append(f"{url}{wildcard}")

    return _stable_dedup(uris) if dedup else uris


class LookupModule(LookupBase):
    """
    Usage:
        {{ lookup('redirect_uris') }}
        {{ lookup('redirect_uris', wildcard='/cb') }}

    Returns the redirect URIs Keycloak must whitelist: one per domain of every
    application whose config enables SSO. Each URI's scheme is resolved for the
    CONSUMER -- its own ``server.tls.enabled`` over the global ``TLS_ENABLED``,
    and always plaintext for an .onion -- never from Keycloak's own TLS state.

    - parameters:
        wildcard: suffix appended to every URI (default '/*')
        features: config paths ORed to gate an application (default services.sso.enabled)
        dedup: drop repeated URIs (default true)
    """

    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[list[str]]:
        if terms:
            raise AnsibleError("lookup('redirect_uris') expects no terms.")

        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        if "TLS_ENABLED" not in variables:
            raise AnsibleError("redirect_uris: TLS_ENABLED is not defined.")

        loader = getattr(self, "_loader", None)
        templar = getattr(self, "_templar", None)
        domains = lookup_loader.get("domains", loader=loader, templar=templar).run(
            [], variables=variables
        )[0]
        applications = lookup_loader.get(
            "applications", loader=loader, templar=templar
        ).run([], variables=variables)[0]

        features = kwargs.get("features") or DEFAULT_FEATURES
        return [
            build_redirect_uris(
                domains,
                applications,
                bool(variables["TLS_ENABLED"]),
                wildcard=kwargs.get("wildcard", DEFAULT_WILDCARD),
                features=features,
                dedup=bool(kwargs.get("dedup", True)),
            )
        ]
