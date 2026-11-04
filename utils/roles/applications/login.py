"""The sign-in methods an application offers and their default per mode."""

from __future__ import annotations

CORE_METHODS = ("sso", "ldap", "native", "2fa")
EXTRA_METHODS = ("passkey", "openid2", "odoo_com", "email", "registration")
METHODS = CORE_METHODS + EXTRA_METHODS


def default(method: str, sso: bool, ldap: bool) -> bool:
    """Whether a sign-in method is on by default.

    Args:
        method: one of ``METHODS``.
        sso: the application's ``services.sso.enabled``.
        ldap: the application's ``services.ldap.enabled``; False for an
            application without an ``ldap`` service.

    Returns:
        With SSO only ``sso``; without SSO but with LDAP ``ldap`` and ``2fa``;
        with neither ``native`` and ``2fa``. Every extra method is off.

    Raises:
        ValueError: for a method outside ``METHODS``.
    """
    if method not in METHODS:
        raise ValueError(f"login method {method!r} is not one of {', '.join(METHODS)}")
    if method == "sso":
        return sso
    if sso or method in EXTRA_METHODS:
        return False
    if method == "ldap":
        return ldap
    if method == "native":
        return not ldap
    return True
