# nocheck: mirrored-unit-test - an Odoo addon manifest, a bare dict literal the registry reads; there is no behaviour to exercise
{  # noqa: B018  Odoo addon manifests are bare dict expressions at module level by design
    "name": "OAuth HTTPS & Configurable UID",
    "version": "1.9.0",
    "category": "Authentication",
    "summary": "Force HTTPS redirect URIs and configurable OIDC UID field for OAuth",
    "description": """
OAuth HTTPS & Configurable UID Field
====================================

This module provides two fixes for OAuth authentication with OIDC providers like Keycloak:

1. HTTPS Redirect URIs
----------------------
The standard auth_oauth module uses request.httprequest.url_root to build redirect URIs,
which may not correctly respect X-Forwarded-Proto headers behind a reverse proxy.

This module overrides that behavior to use the web.base.url system parameter instead,
ensuring consistent HTTPS redirect URIs for OAuth authentication flows.

2. Configurable OIDC UID Field
------------------------------
Standard Odoo uses 'user_id' from the OAuth userinfo response to identify users.
This claim is non-standard; Keycloak maps its internal UUID to it by default.

This module changes user identification to use a configurable claim field,
set via the ODOO_OIDC_UID_FIELD environment variable.
This aligns Odoo with other applications in the infinito.nexus stack:
- Mastodon: OIDC_UID_FIELD = preferred_username
- Pixelfed: PF_OIDC_FIELD_ID = preferred_username
- EspoCRM: OIDC_USERNAME_CLAIM = preferred_username
- Taiga: OIDC_USERNAME_CLAIM = preferred_username

Configuration:
--------------
Set ODOO_OIDC_UID_FIELD environment variable to the OIDC claim to use for user
identification. The deploy renders it from OIDC.ATTRIBUTES.USERNAME.

3. Roles and Profile from the Identity Provider
-----------------------------------------------
Every sign-in reads the groups claim (ODOO_OIDC_GROUP_CLAIM) and refuses a
user that holds none of the declared roles (ODOO_RBAC_ROLES), the platform
administrator excepted. The managed Odoo groups of the user are replaced with
the groups its roles grant, and the profile claims (ODOO_OIDC_*_CLAIM) are
written to name, email, phone, language and time zone.

Features:
---------
* Forces OAuth redirect URIs to use web.base.url
* Configurable OIDC UID field via environment variable
* Role-based sign-in and group sync from the groups claim
* Profile sync from the OIDC claims on every sign-in
* Works correctly behind reverse proxies with TLS termination
* Consistent with infinito.nexus OIDC identity standards
    """,
    "author": "evangelostsak",
    "website": "https://infinito.nexus",
    "depends": ["auth_oauth", "infinito_rbac"],
    "data": [],
    "installable": True,
    "auto_install": False,
    "application": False,
    "license": "Other proprietary",
}
