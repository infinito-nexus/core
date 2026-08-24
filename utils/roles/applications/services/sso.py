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

from utils.roles.applications.config import get

if TYPE_CHECKING:
    from collections.abc import Mapping


_DEFAULT_FLAVOR = "oidc"
_VALID_FLAVORS = frozenset({"oidc", "oauth2", "saml"})


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


def get_sso_config(
    applications: Mapping[str, Any],
    application_id: str,
) -> dict[str, Any]:
    """Resolve the SSO state for a consumer role.

    Returns a dict with keys:
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
    raw_allowed_groups = _get(
        applications, application_id, "services.sso.oauth2.allowed_groups", []
    )

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
        "oauth2_allowed_groups": (
            list(raw_allowed_groups)
            if isinstance(raw_allowed_groups, (list, tuple))
            else []
        ),
    }
