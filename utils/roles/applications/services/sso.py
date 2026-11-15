"""Single-source-of-truth resolver for a role's unified SSO surface.

Reads ``services.sso.{enabled,shared,flavor,oauth2.*}`` from the merged
applications payload and derives the semantic predicates and
flavor-specific sub-values that the SSO-proxy wiring, the redis-sidecar
gating, and the consumer-side playwright env all need.

The flavor enum is ``{oidc, oauth2, saml}`` with ``oidc`` as the default
when omitted. The ``is_proxy_gated`` predicate is the one place that
encodes "the oauth2-proxy sidecar fronts this role" — every other layer
MUST consult this helper instead of re-implementing the
``enabled AND flavor == 'oauth2'`` compound. The ``oauth2_*`` keys
expose the gated upstream config so call sites resolve cross-role data
through one named property rather than a literal ``lookup('config',
app_id, 'services.sso.oauth2.<sub>')`` (which would otherwise trip the
literal-protocol-lookup and lookup-config-path static-scan guards).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from ansible.errors import AnsibleFilterError

from utils.networks.instances import labelled, labelled_file, network_instances
from utils.roles.applications.config import get

if TYPE_CHECKING:
    from collections.abc import Mapping


_DEFAULT_FLAVOR = "oidc"
_VALID_FLAVORS = frozenset({"oidc", "oauth2", "saml"})
OAUTH2_SIGN_OUT_PATH = "/oauth2/sign_out"


class SsoConfigConflictError(AnsibleFilterError, ValueError):
    """Raised when an application's ``services.sso`` keys contradict each other."""


def is_potentially_enabled(value: Any) -> bool:
    """Return True unless the value is statically known to be disabled.

    Jinja templates render at runtime, so any unrendered Jinja string
    (e.g. ``"{{ 'web-app-keycloak' in group_names }}"``) MUST be treated
    as potentially truthy by static-analysis callers (lint tests,
    contract checks).

    Statically disabled means: the value is literal ``False``, ``None``,
    or the string literal ``"false"`` (case-insensitive, whitespace
    trimmed). Everything else is assumed to *possibly* render truthy.

    Use this for static lint checks that walk ``meta/services.yml``
    text. Runtime callers should prefer ``get_sso_config``'s
    ``is_enabled`` predicate, which already runs against the merged +
    rendered payload.
    """
    if value is None or value is False:
        return False
    return not (isinstance(value, str) and value.strip().lower() == "false")


def _as_bool(value: Any) -> bool:
    """Coerce a merged-payload flag to bool.

    Args:
        value: the raw value, which may still be the string a template rendered.

    Returns:
        True only for a literal True or a string spelling an affirmative.
    """
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


def _get(applications: Mapping[str, Any], app_id: str, path: str, default: Any) -> Any:
    """Thin wrapper around ``get`` with the lenient flags this module uses."""
    return get(
        applications=applications,
        application_id=app_id,
        config_path=path,
        strict=False,
        default=default,
        skip_missing_app=True,
    )


def _oauth2_admission(
    applications: Mapping[str, Any], app_id: str
) -> tuple[list[Any], bool]:
    """Resolve who the oauth2 gate admits.

    Args:
        applications: the merged applications payload.
        app_id: the consumer application.

    Returns:
        ``(allowed_groups, allow_all_users)``.

    Raises:
        SsoConfigConflictError: ``allow_all_users`` is true and
            ``allowed_groups`` is non-empty.
    """
    raw_groups = _get(applications, app_id, "services.sso.oauth2.allowed_groups", [])
    allowed_groups = list(raw_groups) if isinstance(raw_groups, (list, tuple)) else []
    allow_all_users = _as_bool(
        _get(applications, app_id, "services.sso.oauth2.allow_all_users", False)
    )
    if allow_all_users and allowed_groups:
        raise SsoConfigConflictError(
            f"{app_id}: services.sso.oauth2.allow_all_users is true while "
            f"services.sso.oauth2.allowed_groups is non-empty ({allowed_groups}). "
            "allow_all_users admits every authenticated realm user, allowed_groups "
            "admits only its members. Set allowed_groups: [] in the inventory to "
            "admit everyone, or drop allow_all_users to keep the restriction."
        )
    return allowed_groups, allow_all_users


def get_sso_config(
    applications: Mapping[str, Any],
    application_id: str,
) -> dict[str, Any]:
    """Resolve the SSO state for a consumer role.

    Returns a dict with keys::

        enabled                 bool — ``services.sso.enabled``
        shared                  bool — ``services.sso.shared``
        flavor                  str  — one of {oidc, oauth2, saml}; default 'oidc'
        is_enabled              bool — alias of ``enabled``, semantic name
        is_proxy_gated          bool — ``enabled AND flavor == 'oauth2'``
        is_oidc_native          bool — ``enabled AND flavor == 'oidc'``
        is_saml                 bool — ``enabled AND flavor == 'saml'``
        oauth2_origin_host      str  — ``services.sso.oauth2.origin.host`` or ''
        oauth2_origin_port      str  — ``services.sso.oauth2.origin.port`` or ''
        oauth2_acl              dict — ``services.sso.oauth2.acl`` or {}
        oauth2_allowed_groups   list — ``services.sso.oauth2.allowed_groups`` or []
        oauth2_allow_all_users  bool - ``services.sso.oauth2.allow_all_users``,
                                default False: the gate admits every
                                authenticated realm user and still forwards
                                the groups claim, so the app derives roles
                                from the groups header itself
        oauth2_pass_access_token bool — ``services.sso.oauth2.pass_access_token``,
                                default False: the gate hands the upstream a
                                bearer token only where the app decodes one
        oauth2_any_email        bool — ``services.sso.oauth2.any_email``,
                                default False: the gate admits a realm user of
                                any email domain, not only ``DOMAIN_PRIMARY``
        oauth2_claim_headers    list — ``services.sso.oauth2.claim_headers`` or []:
                                ``OIDC.ATTRIBUTES`` keys whose ID token claims
                                the gate forwards as ``X-Forwarded-<Key>``
        oauth2_restricted_locations list — ``services.sso.oauth2.restricted_locations``
                                or []: one ``{location, groups, auth_uri,
                                upstream}`` per entry; the gate admits a request
                                to ``location`` only for a member of ``groups``
        oauth2_client           dict — ``services.sso.oauth2.client`` as
                                ``{id, scopes}``, or {} when the gate signs in
                                through the shared client

    ``allow_all_users`` true together with a non-empty ``allowed_groups``
    raises ``SsoConfigConflictError``. A list in the inventory replaces the
    role's list, so ``allowed_groups: []`` there clears what
    ``meta/services.yml`` ships.

    The compound predicates are the documented call surface — call sites
    should prefer ``is_proxy_gated`` over manually combining
    ``enabled`` and ``flavor``. The ``oauth2_*`` fields are the documented
    way to read the gated upstream config; templates that previously
    spelled out ``lookup('config', app_id, 'services.sso.oauth2.<sub>')``
    SHOULD use ``lookup('sso', app_id, 'oauth2_<sub>')`` instead so the
    Python-side helper and the Ansible-side lookup share one schema.
    """
    enabled = bool(_get(applications, application_id, "services.sso.enabled", False))
    shared = bool(_get(applications, application_id, "services.sso.shared", False))
    raw_flavor = _get(
        applications, application_id, "services.sso.flavor", _DEFAULT_FLAVOR
    )
    flavor = str(raw_flavor).strip() if isinstance(raw_flavor, str) else _DEFAULT_FLAVOR
    if flavor not in _VALID_FLAVORS:
        flavor = _DEFAULT_FLAVOR

    raw_host = _get(applications, application_id, "services.sso.oauth2.origin.host", "")
    raw_port = _get(applications, application_id, "services.sso.oauth2.origin.port", "")
    raw_acl = _get(applications, application_id, "services.sso.oauth2.acl", {})
    raw_pass_access_token = _get(
        applications, application_id, "services.sso.oauth2.pass_access_token", False
    )
    raw_any_email = _get(
        applications, application_id, "services.sso.oauth2.any_email", False
    )
    raw_claim_headers = _get(
        applications, application_id, "services.sso.oauth2.claim_headers", []
    )
    raw_restricted = _get(
        applications, application_id, "services.sso.oauth2.restricted_locations", []
    )
    raw_client = _get(applications, application_id, "services.sso.oauth2.client", {})
    allowed_groups, allow_all_users = _oauth2_admission(applications, application_id)

    return {
        "enabled": enabled,
        "shared": shared,
        "flavor": flavor,
        "is_enabled": enabled,
        "is_proxy_gated": enabled and flavor == "oauth2",
        "is_oidc_native": enabled and flavor == "oidc",
        "is_saml": enabled and flavor == "saml",
        "oauth2_origin_host": str(raw_host) if raw_host else "",
        "oauth2_origin_port": str(raw_port) if raw_port not in (None, "") else "",
        "oauth2_acl": raw_acl if isinstance(raw_acl, dict) else {},
        "oauth2_allowed_groups": allowed_groups,
        "oauth2_allow_all_users": allow_all_users,
        "oauth2_pass_access_token": _as_bool(raw_pass_access_token),
        "oauth2_any_email": _as_bool(raw_any_email),
        "oauth2_claim_headers": (
            [str(key) for key in raw_claim_headers]
            if isinstance(raw_claim_headers, (list, tuple))
            else []
        ),
        "oauth2_restricted_locations": restricted_locations(raw_restricted),
        "oauth2_client": oauth2_client(application_id, raw_client),
    }


def oauth2_client(app_id: str, raw: Any) -> dict[str, Any]:
    """
    Args:
        app_id: the consumer application.
        raw: ``services.sso.oauth2.client``, a ``{id, scopes}`` mapping or empty.

    Returns:
        ``{}`` when the application declares no client of its own, else
        ``{"id", "scopes"}``: the client id and the default client scopes it
        carries beyond the shared login scopes.

    Raises:
        ValueError: a declared client without an id or without a scope list.
    """
    if not raw:
        return {}
    client_id = str(raw.get("id") or "").strip() if isinstance(raw, dict) else ""
    scopes = raw.get("scopes") if isinstance(raw, dict) else None
    if not client_id or not isinstance(scopes, (list, tuple)):
        raise ValueError(
            f"{app_id}: services.sso.oauth2.client needs an id and a scopes list"
        )
    return {"id": client_id, "scopes": [str(scope).strip() for scope in scopes]}


def restricted_locations(raw: Any) -> list[dict[str, Any]]:
    """Return the per-location group gates of an oauth2-proxy gated application.

    Args:
        raw: ``services.sso.oauth2.restricted_locations``, a list of
            ``{location, groups}`` mappings.

    Returns:
        One mapping per entry with the ``location``, the ``groups`` (each with
        one leading slash, as the groups claim carries them), the internal
        ``auth_uri`` nginx asks and the ``upstream`` path that URI proxies to.

    Raises:
        ValueError: an entry without a location or without groups.
    """
    if not isinstance(raw, (list, tuple)):
        return []
    gates = []
    for index, entry in enumerate(raw):
        location = str((entry or {}).get("location") or "").strip()
        groups = [
            "/" + str(group).lstrip("/") for group in (entry or {}).get("groups") or []
        ]
        if not location or not groups:
            raise ValueError(
                f"restricted_locations[{index}] needs a location and at least one group"
            )
        gates.append(
            {
                "location": location,
                "groups": groups,
                "auth_uri": f"/oauth2/auth-restricted-{index}",
                "upstream": "/oauth2/auth?allowed_groups="
                + ",".join(quote(group, safe="/") for group in groups),
            }
        )
    return gates


def proxy_instances(
    app_domains: Any, config_file: str, alpha_config_file: str
) -> list[dict[str, str]]:
    """Return the oauth2-proxy instances a gated application runs.

    One oauth2-proxy applies one cookie-secure flag to every host it answers,
    and a secure flag drops the CSRF cookie on a plaintext onion sibling, so an
    application served on several networks runs one instance per network.

    Args:
        app_domains: the application's entry of ``lookup('domains')``: a
            domain, a list of domains or a ``{key: domain}`` mapping.
        config_file: ``web-app-keycloak``'s
            ``services.sso_proxy.configuration_file``.
        alpha_config_file: ``web-app-keycloak``'s
            ``services.sso_proxy.alpha_configuration_file``.

    Returns:
        One mapping per network, in the order the domains name them, with
        ``network``, the compose ``service``, the ``port_key`` under
        ``ports.local``, the ``config_file`` and the ``alpha_config_file``
        the instance reads. The canonical network keeps the unsuffixed names;
        each further network appends its registry label.
    """
    return [
        {
            "network": instance["network"],
            "service": labelled("sso-proxy", instance["label"], "-"),
            "port_key": labelled("sso", instance["label"], "_"),
            "config_file": labelled_file(config_file, instance["label"]),
            "alpha_config_file": labelled_file(alpha_config_file, instance["label"]),
        }
        for instance in network_instances(app_domains)
    ]


def logout_url(oidc_logout_url: str, is_proxy_gated: bool) -> str:
    """Return the logout target of an application's own logout control.

    Args:
        oidc_logout_url: the identity provider's end-session endpoint.
        is_proxy_gated: whether oauth2-proxy fronts the application.
    """
    if not is_proxy_gated:
        return oidc_logout_url
    return f"{OAUTH2_SIGN_OUT_PATH}?rd={quote(oidc_logout_url, safe='/')}"
